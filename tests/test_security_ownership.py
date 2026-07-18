import unittest
from unittest.mock import patch

from fastapi import HTTPException


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        rows = [
            row
            for row in self.rows
            if all(str(row.get(key)) == str(value) for key, value in self.filters.items())
        ]
        return _Result(rows)


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        if name != "brand_passports":
            raise AssertionError(f"unexpected table {name}")
        return _FakeQuery(self.rows)


class OrgOwnershipTests(unittest.TestCase):
    def test_missing_org_is_created_before_onboarding_can_write_fk_rows(self):
        import main

        events = []

        class OrgQuery:
            def __init__(self):
                self.mode = "select"

            def select(self, *_args):
                self.mode = "select"
                return self

            def eq(self, *_args):
                return self

            def limit(self, *_args):
                return self

            def insert(self, payload):
                self.mode = "insert"
                self.payload = payload
                return self

            def execute(self):
                if self.mode == "insert":
                    events.append(("insert", self.payload))
                    return _Result([self.payload])
                return _Result([])

        class OrgSupabase:
            def table(self, name):
                self.asserted_table = name
                return OrgQuery()

        client = OrgSupabase()
        with patch.object(main, "get_supabase", return_value=client):
            main._ensure_org_exists("org-new", "Northstar Books")

        self.assertEqual(client.asserted_table, "orgs")
        self.assertEqual(events, [("insert", {"id": "org-new", "name": "Northstar Books"})])

    def test_existing_org_is_not_inserted_twice(self):
        import main

        class ExistingOrgQuery:
            def select(self, *_args):
                return self

            def eq(self, *_args):
                return self

            def limit(self, *_args):
                return self

            def insert(self, _payload):
                raise AssertionError("existing org must not be inserted")

            def execute(self):
                return _Result([{"id": "org-existing"}])

        class ExistingOrgSupabase:
            def table(self, name):
                self.asserted_table = name
                return ExistingOrgQuery()

        client = ExistingOrgSupabase()
        with patch.object(main, "get_supabase", return_value=client):
            main._ensure_org_exists("org-existing", "Existing Brand")

        self.assertEqual(client.asserted_table, "orgs")

    def test_user_must_own_org_id_before_org_scoped_routes_run(self):
        import main

        rows = [
            {
                "id": "passport-1",
                "org_id": "org-owned",
                "owner_user_id": "user-owned",
            },
            {
                "id": "passport-2",
                "org_id": "org-other",
                "owner_user_id": "user-other",
            },
        ]

        with (
            patch.object(main, "get_supabase", return_value=_FakeSupabase(rows)),
            patch.object(main, "_ensure_org_exists") as ensure_org,
        ):
            main._assert_user_owns_org("user-owned", "org-owned")
            ensure_org.assert_called_once_with("org-owned", "Untitled brand")

            with self.assertRaises(HTTPException) as mismatch:
                main._assert_user_owns_org("user-owned", "org-other")
            self.assertEqual(mismatch.exception.status_code, 403)
            self.assertEqual(mismatch.exception.detail, "Org does not belong to this user")

            with self.assertRaises(HTTPException) as missing:
                main._assert_user_owns_org("user-owned", "org-missing")
            self.assertEqual(missing.exception.status_code, 403)
            self.assertEqual(missing.exception.detail, "Org is not linked to this user")

    def test_onboarding_owner_path_must_match_authenticated_user(self):
        import main

        main._assert_onboarding_owner(main.AuthContext(user_id="user-1"), "user-1")

        with self.assertRaises(HTTPException) as mismatch:
            main._assert_onboarding_owner(main.AuthContext(user_id="user-1"), "user-2")
        self.assertEqual(mismatch.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
