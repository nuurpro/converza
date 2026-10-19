import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[1]


class EvalEntrypointTests(unittest.TestCase):
    def test_documented_memory_script_runs_without_pythonpath(self):
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        result = subprocess.run([sys.executable, "evals/memory/run.py"], cwd=CORE, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 1.0)

    def test_workflow_cli_loads_backend_environment(self):
        module = importlib.import_module("services.workflow.evals.run")
        with patch("dotenv.load_dotenv") as load, contextlib.redirect_stdout(io.StringIO()):
            code = module.cli([])
        self.assertEqual(code, 0)
        load.assert_called_once_with(CORE / ".env")

    def test_documented_backfill_help_runs_without_pythonpath_or_database_calls(self):
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        result = subprocess.run([sys.executable, "scripts/backfill_memory.py", "--help"], cwd=CORE, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--apply", result.stdout)
