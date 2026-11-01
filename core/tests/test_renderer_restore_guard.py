import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('renderer_restore',Path(__file__).resolve().parents[2]/'scripts/verify_renderer_restore.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RestoreGuardTests(unittest.TestCase):
    def test_credentials_can_only_be_sent_to_a_fixed_loopback_origin(self):
        with patch.object(module.httpx,'Client') as client, patch.object(module.subprocess,'run') as docker:
            for origin in ('https://external.invalid','http://127.0.0.1@external.invalid','http://user:key@127.0.0.1:8080',
                           'http://127.0.0.1:8080/path','http://127.0.0.1:8080?next=external'):
                with self.subTest(origin=origin),self.assertRaises(ValueError):
                    module.verify(Path('/unused'),'renderer',origin,'private')
            client.assert_not_called();docker.assert_not_called()
            with self.assertRaises(ValueError):module.verify(Path('/unused'),'../renderer','http://127.0.0.1:8080','private')
            docker.assert_not_called()

    def test_changed_receipt_state_fails_before_http_readiness_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'files.json').write_text('[]')
            (root/'report.json').write_text(json.dumps({'receipts':1,'receipt_digest':'expected'}))
            changed={'files_checked':0,'mismatches':[],'integrity':['ok'],'receipts':1,'receipt_digest':'changed'}
            with patch.object(module.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps(changed))), \
                    patch.object(module.httpx,'Client') as client:
                with self.assertRaises(RuntimeError):module.verify(root,'renderer','http://127.0.0.1:8080','private')
                client.assert_not_called()
