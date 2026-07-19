import asyncio
import unittest
from unittest.mock import patch

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.filters = {}
        self.pending_update = None

    def select(self, *_args, **_kwargs):
        return self

    def update(self, payload):
        self.pending_update = dict(payload)
        self.client.last_update = dict(payload)
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        self.client.last_limit = _args[0] if _args else None
        return self

    def execute(self):
        rows = self.client.tables.get(self.table_name, [])
        matches = [
            row for row in rows
            if all(str(row.get(key)) == str(value) for key, value in self.filters.items())
        ]
        if self.pending_update is not None:
            for row in matches:
                row.update(self.pending_update)
        return _Result([dict(row) for row in matches])


class _Client:
    def __init__(self):
        self.tables = {
            "brand_passports": [
                {
                    "id": "passport-1",
                    "org_id": "org-1",
                    "owner_user_id": "user-1",
                    "brand_name": "Northstar",
                    "owner_name": "Nora",
                    "owner_role": None,
                    "tone": "friendly",
                    "target_audience": "Shopify founders",
                    "core_offer": "Managed campaigns",
                    "target_location": "United States",
                    "channels_requested": ["instagram"],
                    "paywall_status": "stub_completed",
                    "selected_plan": "pilot",
                    "updated_at": "2026-07-01T00:00:00+00:00",
                }
            ],
            "agent_memory": [
                {
                    "id": "memory-1",
                    "org_id": "org-1",
                    "agent_slug": "milo",
                    "role": "assistant",
                    "content": "Use concise campaign hooks.",
                    "created_at": "2026-07-01T00:00:00+00:00",
                },
                {
                    "id": "memory-2",
                    "org_id": "org-1",
                    "agent_slug": "sleyz",
                    "role": "assistant",
                    "content": "Ask before offering a discount.",
                    "created_at": "2026-07-02T00:00:00+00:00",
                },
            ],
        }
        self.last_update = None
        self.last_limit = None

    def table(self, table_name):
        return _Query(self, table_name)


class SettingsRepositoryTests(unittest.TestCase):
    def test_repository_round_trips_only_supplied_fields(self):
        from lib.settings_repository import SettingsRepository

        client = _Client()
        repo = SettingsRepository(client)

        self.assertEqual(repo.get_passport("org-1")["brand_name"], "Northstar")
        updated = repo.update_passport(
            "org-1",
            {"tone": "direct, warm"},
            expected_updated_at="2026-07-01T00:00:00+00:00",
        )

        self.assertEqual(updated["tone"], "direct, warm")
        self.assertEqual(client.last_update["tone"], "direct, warm")
        self.assertNotIn("brand_name", client.last_update)

    def test_repository_returns_real_org_memory(self):
        from lib.settings_repository import SettingsRepository

        client = _Client()
        rows = SettingsRepository(client).get_memory("org-1")

        self.assertEqual([row["agent_slug"] for row in rows], ["milo", "sleyz"])
        self.assertEqual(rows[0]["content"], "Use concise campaign hooks.")
        self.assertEqual(client.last_limit, 100)

    def test_repository_rejects_stale_revision(self):
        from lib.settings_repository import SettingsConflictError, SettingsRepository

        with self.assertRaises(SettingsConflictError):
            SettingsRepository(_Client()).update_passport(
                "org-1",
                {"tone": "formal"},
                expected_updated_at="2026-06-01T00:00:00+00:00",
            )


class SettingsRouteTests(unittest.TestCase):
    def test_update_rejects_unknown_and_blank_fields(self):
        import main
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as unknown:
            main._validate_settings_updates({"fake_subscription": "active"})
        self.assertEqual(unknown.exception.status_code, 400)

        with self.assertRaises(HTTPException) as blank:
            main._validate_settings_updates({"tone": "   "})
        self.assertEqual(blank.exception.status_code, 400)

        with self.assertRaises(HTTPException) as empty:
            main._validate_settings_updates({})
        self.assertEqual(empty.exception.status_code, 400)

    def test_owned_settings_route_updates_passport(self):
        import main
        from lib.settings_repository import SettingsRepository

        client = _Client()
        request = main.WorkspaceSettingsUpdateRequest(
            org_id="org-1",
            updates={"owner_role": "Founder"},
            expected_updated_at="2026-07-01T00:00:00+00:00",
        )
        with (
            patch.object(main, "_assert_user_owns_org") as ownership,
            patch.object(main, "get_settings_repo", return_value=SettingsRepository(client)),
        ):
            result = asyncio.run(
                main.update_workspace_settings(request, main.AuthContext(user_id="user-1"))
            )

        ownership.assert_called_once_with("user-1", "org-1")
        self.assertEqual(result["settings"]["owner_role"], "Founder")

    def test_stale_settings_revision_is_rejected(self):
        import main
        from fastapi import HTTPException
        from lib.settings_repository import SettingsRepository

        request = main.WorkspaceSettingsUpdateRequest(
            org_id="org-1",
            updates={"tone": "formal"},
            expected_updated_at="2026-06-01T00:00:00+00:00",
        )
        with (
            patch.object(main, "_assert_user_owns_org"),
            patch.object(main, "get_settings_repo", return_value=SettingsRepository(_Client())),
            self.assertRaises(HTTPException) as raised,
        ):
            asyncio.run(
                main.update_workspace_settings(request, main.AuthContext(user_id="user-1"))
            )

        self.assertEqual(raised.exception.status_code, 409)

    def test_stub_completion_records_plan_without_claiming_payment(self):
        import main
        from fastapi import HTTPException

        self.assertEqual(
            main._stub_payment_updates("pilot"),
            {"paywall_status": "stub_completed", "selected_plan": "pilot"},
        )
        with self.assertRaises(HTTPException):
            main._stub_payment_updates("invented-plan")

    def test_missing_settings_columns_report_pending_migration(self):
        import main
        from fastapi import HTTPException

        missing_column = Exception(
            "{'message': 'column brand_passports.owner_role does not exist', "
            "'code': '42703'}"
        )
        with self.assertRaises(HTTPException) as raised:
            main._raise_settings_migration_error(missing_column)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("006_settings_real_data.sql", raised.exception.detail)


class SettingsContextRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_updated_tone_is_loaded_by_next_context_assembly(self):
        from lib.context_assembler import assemble_context

        class MutableRepo:
            def __init__(self):
                self.passport = {"org_id": "org-1", "brand_name": "Northstar", "tone": "friendly"}

            async def get_brand_passport(self, _org_id):
                return dict(self.passport)

            async def get_agent_memory(self, _org_id, _agent_slug, limit=20):
                return []

        repo = MutableRepo()
        first = await assemble_context("org-1", "milo", repo=repo)
        repo.passport["tone"] = "concise, formal, evidence-led"
        second = await assemble_context("org-1", "milo", repo=repo)

        self.assertEqual(first["brand_passport"]["tone"], "friendly")
        self.assertEqual(second["brand_passport"]["tone"], "concise, formal, evidence-led")


if __name__ == "__main__":
    unittest.main()
