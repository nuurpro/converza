import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('workspace_snapshot',Path(__file__).resolve().parents[2]/'scripts/snapshot_workspace_database.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WorkspaceSnapshotTests(unittest.TestCase):
    def test_requires_quiescence_and_private_destination_before_network(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(module.httpx,'Client') as client:
            root=Path(raw)
            for destination,quiesced in ((root/'new',False),(root,True)):
                with self.assertRaises(ValueError):
                    module.snapshot({},destination,root,expected_counts={},quiesced=quiesced)
            client.assert_not_called()

    def test_never_sends_keys_to_non_https_credential_or_path_origins(self):
        for origin in ('http://db.example','https://user:pass@db.example','https://db.example/private',
                       'https://db.example?next=other'):
            with self.subTest(origin=origin),self.assertRaises(ValueError):
                module.source_origin(origin)

    def test_changed_rows_are_not_saved(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(module.httpx,'Client'), \
                patch.object(module,'collect',side_effect=[{'drafts':[{'id':'one'}]},{'drafts':[]}]), \
                patch.object(module,'secure_directory') as secure:
            with self.assertRaises(RuntimeError):
                module.snapshot({'SUPABASE_URL':'https://db.example','SUPABASE_SERVICE_KEY':'sb_secret_fixture'},
                                Path(raw)/'new',Path(raw),expected_counts={t:0 for t in module.TABLES},quiesced=True)
            secure.assert_not_called()

    def test_verified_snapshot_report_contains_no_row_contents_or_credentials(self):
        with tempfile.TemporaryDirectory() as raw, patch.object(module.httpx,'Client') as client, \
                patch.object(module,'collect',return_value={t:([{'id':'one','content':'private fixture'}] if t=='drafts' else []) for t in module.TABLES}):
            report=module.snapshot({'SUPABASE_URL':'https://db.example','SUPABASE_SERVICE_KEY':'sb_secret_fixture-secret'},
                                   Path(raw)/'new',Path(raw),expected_counts={t:int(t=='drafts') for t in module.TABLES},quiesced=True)
            self.assertTrue(report['double_read_verified'])
            self.assertNotIn('private fixture',str(report))
            self.assertNotIn('fixture-secret',str(report))
            self.assertFalse(client.call_args.kwargs['follow_redirects'])
            self.assertFalse(client.call_args.kwargs['trust_env'])

    def test_rls_filtered_empty_reads_cannot_be_certified(self):
        with tempfile.TemporaryDirectory() as raw,patch.object(module.httpx,'Client'), \
                patch.object(module,'collect',return_value={t:[] for t in module.TABLES}), \
                patch.object(module,'secure_directory') as secure:
            with self.assertRaisesRegex(RuntimeError,'visibility/count mismatch'):
                module.snapshot({'SUPABASE_URL':'https://db.example','SUPABASE_SERVICE_KEY':'sb_secret_fixture'},
                                Path(raw)/'new',Path(raw),expected_counts={t:(5 if t=='brand_passports' else 0) for t in module.TABLES},quiesced=True)
            secure.assert_not_called()

    def test_anon_and_malformed_credentials_are_rejected(self):
        for key in ('public','x.eyJyb2xlIjoiYW5vbiJ9.x','x.eyJyb2xlIjoiYXV0aGVudGljYXRlZCJ9.x'):
            with self.subTest(key=key),self.assertRaises(ValueError):
                module.privileged_key(key)
        self.assertEqual(module.privileged_key('x.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.x'),'service_role')
