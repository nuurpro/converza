"""Real, disposable PostgreSQL verification of workspace creation and recovery."""
import concurrent.futures
import os
from pathlib import Path
import threading
import unittest
import uuid

import test_workflow_postgres as workflow


@unittest.skipUnless(os.getenv('CONVERZA_WORKFLOW_TEST_DSN'), 'requires isolated PostgreSQL test database')
class WorkspacePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow.PostgresWorkflowTests.setUpClass()
        cls.connect = staticmethod(workflow.PostgresWorkflowTests.connect)
        base = Path(__file__).resolve().parents[1] / 'migrations'
        with cls.connect() as c, c.cursor() as q:
            q.execute('CREATE SCHEMA IF NOT EXISTS auth; CREATE TABLE IF NOT EXISTS auth.users(id uuid PRIMARY KEY)')
            q.execute('ALTER TABLE orgs ADD COLUMN IF NOT EXISTS name text, ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()')
            q.execute((base / '003_onboarding_paywall.sql').read_text())
            q.execute('''ALTER TABLE brand_passports ADD COLUMN IF NOT EXISTS tone text,
              ADD COLUMN IF NOT EXISTS industry text,ADD COLUMN IF NOT EXISTS core_offer text,
              ADD COLUMN IF NOT EXISTS target_audience text,ADD COLUMN IF NOT EXISTS target_location text,
              ADD COLUMN IF NOT EXISTS hex_colors text[]''')
            q.execute((base / '011_workspace_restore.sql').read_text())

    def setUp(self):
        self.owner = str(uuid.uuid4())
        with self.connect() as c, c.cursor() as q:
            q.execute('INSERT INTO auth.users(id) VALUES(%s)', (self.owner,))

    def tearDown(self):
        with self.connect() as c, c.cursor() as q:
            q.execute('SELECT org_id FROM brand_passports WHERE owner_user_id=%s', (self.owner,))
            orgs = [row[0] for row in q.fetchall() if row[0]]
            q.execute('DELETE FROM brand_passports WHERE owner_user_id=%s', (self.owner,))
            for org in orgs:
                q.execute('DELETE FROM orgs WHERE id=%s', (org,))
            q.execute('DELETE FROM auth.users WHERE id=%s', (self.owner,))

    def save(self, expected=None, payload=None):
        from psycopg2.extras import Json
        with self.connect() as c, c.cursor() as q:
            q.execute('SELECT workspace_save_passport(%s,%s,%s)', (self.owner, expected, Json(payload or {'brand_name': 'Ministry initiative'})))
            return q.fetchone()[0]

    def test_concurrent_first_save_has_one_persisted_workspace(self):
        barrier = threading.Barrier(4)
        def create(_):
            barrier.wait()
            return self.save()['org_id']
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            ids = list(pool.map(create, range(4)))
        self.assertEqual(len(set(ids)), 1)
        with self.connect() as c, c.cursor() as q:
            q.execute('SELECT count(*) FROM brand_passports WHERE owner_user_id=%s', (self.owner,))
            self.assertEqual(q.fetchone()[0], 1)

    def test_save_preserves_org_and_completion_and_payment(self):
        original = self.save()
        with self.connect() as c, c.cursor() as q:
            q.execute("UPDATE brand_passports SET onboarding_completed_at=now(),paywall_status='paid' WHERE id=%s", (original['id'],))
        result = self.save(payload={'brand_name': 'Updated', 'org_id': str(uuid.uuid4()), 'owner_user_id': str(uuid.uuid4()), 'paywall_status': 'pending'})
        self.assertEqual(result['org_id'], original['org_id'])
        self.assertEqual(result['owner_user_id'], self.owner)
        self.assertEqual(result['paywall_status'], 'paid')
        self.assertTrue(result['onboarding_completed_at'])
        with self.assertRaisesRegex(Exception, 'workspace_ownership'):
            self.save(expected=str(uuid.uuid4()))

    def test_unresolved_existing_passport_cannot_create_duplicate_org(self):
        with self.connect() as c, c.cursor() as q:
            q.execute('INSERT INTO brand_passports(owner_user_id) VALUES(%s)', (self.owner,))
        with self.assertRaisesRegex(Exception, 'workspace_ownership'):
            self.save()

    def test_failure_rolls_back_new_org_and_passport(self):
        with self.connect() as c, c.cursor() as q:
            q.execute('SELECT count(*) FROM orgs')
            before = q.fetchone()[0]
        with self.assertRaises(Exception):
            self.save(payload={'brand_name': 'Rollback', 'current_marketing_spend': 'not-a-number'})
        with self.connect() as c, c.cursor() as q:
            q.execute('SELECT count(*) FROM orgs')
            self.assertEqual(q.fetchone()[0], before)
            q.execute('SELECT count(*) FROM brand_passports WHERE owner_user_id=%s', (self.owner,))
            self.assertEqual(q.fetchone()[0], 0)

    def test_service_only_and_unowned_client_scope_rejected(self):
        with self.connect() as c, c.cursor() as q:
            for role in ('anon', 'authenticated', 'service_role'):
                q.execute("SELECT has_function_privilege(%s,'workspace_save_passport(uuid,uuid,jsonb)','EXECUTE')", (role,))
                self.assertEqual(q.fetchone()[0], role == 'service_role')
        with self.assertRaisesRegex(Exception, 'workspace_ownership'):
            self.save(expected=str(uuid.uuid4()))
