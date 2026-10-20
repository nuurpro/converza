import json
from pathlib import Path
import subprocess
import sys
import unittest


class VeaEvalTests(unittest.TestCase):
    def test_fixture_evaluation_requires_all_source_safety_cases(self):
        result=subprocess.run([sys.executable,'-m','services.vea.evals.run'],cwd=Path(__file__).resolve().parents[1],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report['safety'],1)
        self.assertEqual(report['quality'],1)
        self.assertGreaterEqual(len(report['cases']),6)
