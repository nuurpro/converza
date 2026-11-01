"""Workspace writes must be atomic and never invent a browser recovery tenant."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class WorkspaceRestoreTests(unittest.TestCase):
    def test_save_delegates_owner_and_optional_expected_scope_to_transaction(self):
        import main
        sb = Mock()
        query = sb.table.return_value
        for method in ("select", "eq", "order", "limit"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=[])
        sb.rpc.return_value.execute.return_value = SimpleNamespace(data={"id": "passport", "org_id": "persisted"})
        with patch.object(main, "get_supabase", return_value=sb):
            result = main._save_onboarding_passport("owner", None, {"business_name": "Festival"})
        self.assertEqual(result["org_id"], "persisted")
        sb.table.assert_not_called()
        name, params = sb.rpc.call_args.args
        self.assertEqual(name, "workspace_save_passport")
        self.assertEqual(params["p_owner"], "owner")
        self.assertIsNone(params["p_expected_org"])
        self.assertEqual(params["p_payload"]["brand_name"], "Festival")

    def test_restore_rejects_duplicate_or_unlinked_owner_passports(self):
        import main
        for rows in ([{"id": "a", "org_id": None}], [{"id": "a", "org_id": "one"}, {"id": "b", "org_id": "two"}]):
            sb = Mock()
            query = sb.table.return_value
            for method in ("select", "eq", "order", "limit"):
                getattr(query, method).return_value = query
            query.execute.return_value = SimpleNamespace(data=rows)
            with patch.object(main, "get_supabase", return_value=sb):
                with self.assertRaisesRegex(ValueError, "ownership"):
                    main._get_onboarding_passport("owner")
