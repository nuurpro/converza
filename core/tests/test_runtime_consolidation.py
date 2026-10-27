import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib.context_assembler import load_identity_file


class RuntimeConsolidationTests(unittest.TestCase):
    def test_vea_identity_requires_approved_scripts(self):
        identity = load_identity_file('vea')
        self.assertIn('Approved-script video production specialist', identity)
        self.assertIn('Never invents or rewrites approved narration', identity)

    def test_environment_is_explicit_and_process_values_win(self):
        from services.runtime import load_environment
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('CONVERZA_TEST_SETTING=file\nCONVERZA_TEST_OTHER=loaded\n', encoding='utf-8')
            with patch.dict(os.environ, {'CONVERZA_TEST_SETTING': 'process'}, clear=True):
                load_environment(path)
                self.assertEqual(os.environ['CONVERZA_TEST_SETTING'], 'process')
                self.assertEqual(os.environ['CONVERZA_TEST_OTHER'], 'loaded')

    def test_default_environment_is_canonical_core(self):
        from services.runtime import CORE_DIR, load_environment
        with patch('services.runtime.load_dotenv') as loader:
            load_environment()
        self.assertEqual(CORE_DIR, Path(__file__).resolve().parents[1])
        loader.assert_called_once_with(CORE_DIR / '.env', override=False)
