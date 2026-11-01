"""Single-statement SQL parity gate. Never uses a production database."""
import asyncio
import os
from pathlib import Path
import unittest
import uuid

from lib.repository import InMemoryRepository, SupabaseRepository
from services.feed import PendingFeedStore
from services.milo.store import MiloStore


@unittest.skipUnless(os.getenv('CONVERZA_FEED_TEST_DSN'), 'requires isolated CONVERZA_FEED_TEST_DSN')
class PendingFeedPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pg_supabase import PgSupabase
        cls.client = PgSupabase(os.environ['CONVERZA_FEED_TEST_DSN'])
        with cls.client.connect() as conn, conn.cursor() as q:
            if not conn.info.dbname.startswith('test_converza_feed'):
                raise RuntimeError('Pending feed gate requires its own test_converza_feed database')
            # Minimal public tables model the projection's read-only boundary. This
            # deliberately avoids replacing other sessions' lifecycle RPCs.
            q.execute('''
                DO $$ BEGIN CREATE ROLE service_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                CREATE TABLE IF NOT EXISTS drafts(id uuid PRIMARY KEY,org_id uuid NOT NULL,
                 agent_slug text,revision bigint NOT NULL,status text,created_at timestamptz NOT NULL,
                 draft_content text,superseded_by uuid,vea_artifact jsonb);
                CREATE TABLE IF NOT EXISTS milo_campaigns(id uuid PRIMARY KEY,org_id uuid NOT NULL,
                 revision bigint NOT NULL,status text,script_status text,created_at timestamptz NOT NULL,
                 artifact jsonb,compliance jsonb NOT NULL DEFAULT '{}',missing_evidence jsonb NOT NULL DEFAULT '[]',build_status text);
            ''')
            q.execute(cls.migration())
        cls.repo = SupabaseRepository(cls.client)

    @staticmethod
    def migration():
        return (Path(__file__).resolve().parents[1] / 'migrations/012_pending_feed.sql').read_text(encoding='utf-8')

    def setUp(self):
        self.org, self.foreign = str(uuid.uuid4()), str(uuid.uuid4())
        self.memory = InMemoryRepository()
        self.milo = MiloStore(self.memory)

    def tearDown(self):
        with self.client.connect() as conn, conn.cursor() as q:
            q.execute('DELETE FROM drafts WHERE org_id IN (%s,%s)', (self.org,self.foreign))
            q.execute('DELETE FROM milo_campaigns WHERE org_id IN (%s,%s)', (self.org,self.foreign))

    def seed(self, kind, **changes):
        from psycopg2.extras import Json
        id = changes.pop('id', str(uuid.uuid4()))
        values = dict(id=id, org_id=self.org, revision=3, created_at='2026-01-01T12:00:00Z')
        if kind == 'workflow':
            values.update(agent_slug='sleyz',status='AWAITING_HITL',draft_content='Verified reply',superseded_by=None,vea_artifact=None)
        else:
            values.update(status='awaiting_review',script_status='pending',artifact={'trigger_reason':'Verified buyer objection'},
                          compliance={'passed':True},missing_evidence=[],build_status=None)
        values.update(changes)
        table = 'drafts' if kind == 'workflow' else 'milo_campaigns'
        self.client.table(table).insert({key:Json(value) if isinstance(value,list) else value for key,value in values.items()}).execute()
        row = self.client.table(table).select('*').eq('id',id).execute().data[0]
        if kind == 'workflow':
            self.memory.drafts.append(row)
        else:
            self.milo.state['campaigns'][id] = row
        return row

    def pending(self, **kwargs):
        return asyncio.run(PendingFeedStore(self.repo).pending(self.org, **kwargs))

    def test_mixed_pages_match_memory_with_tenant_and_status_filters(self):
        same = str(uuid.uuid4())
        self.seed('workflow',id=same)
        self.seed('milo',id=same,status='blocked',compliance={'passed':False,'violations':['Unverified grant']})
        self.seed('workflow',created_at='2026-01-01T11:00:00Z')
        self.seed('milo',status='needs_evidence',artifact=None,missing_evidence=['Confirm admission conditions'])
        self.seed('workflow',org_id=self.foreign)
        self.seed('milo',org_id=self.foreign)
        self.seed('workflow',status='REJECTED')
        self.seed('workflow',superseded_by=str(uuid.uuid4()))
        self.seed('workflow',vea_artifact={'superseded':True})
        self.seed('milo',script_status='approved')
        cursor = None
        actual = []
        while True:
            page = self.pending(limit=1,cursor=cursor)
            actual.extend(page['items'])
            cursor = page['next_cursor']
            if not cursor:
                break
        expected = asyncio.run(PendingFeedStore(self.memory).pending(self.org))['items']
        self.assertEqual(actual,expected)
        self.assertEqual(len(actual),4)

    def test_single_snapshot_does_not_observe_partial_cross_lifecycle_commit(self):
        draft = self.seed('workflow')
        campaign = self.seed('milo',status='blocked',compliance={'passed':False})
        with self.client.connect() as writer, writer.cursor() as q:
            q.execute("UPDATE drafts SET status='APPROVED',revision=revision+1 WHERE id=%s",(draft['id'],))
            q.execute("UPDATE milo_campaigns SET script_status='rejected',revision=revision+1 WHERE id=%s",(campaign['id'],))
            self.assertEqual(len(self.pending()['items']),2)  # uncommitted decisions invisible
        self.assertEqual(self.pending()['items'],[])

    def test_null_and_empty_artifacts_cannot_approve_and_reapply_retains_rpc_privileges(self):
        empty = self.seed('milo',artifact=None)
        self.seed('milo',artifact={})
        with self.client.connect() as conn, conn.cursor() as q:
            q.execute("UPDATE milo_campaigns SET artifact='null'::jsonb WHERE id=%s",(empty['id'],))
        for row in self.pending()['items']:
            self.assertFalse(row['restrictions']['can_approve'])
        with self.client.connect() as conn, conn.cursor() as q:
            q.execute(self.migration())
            for role in ('anon','authenticated','service_role'):
                q.execute("SELECT has_function_privilege(%s,'pending_approval_feed(uuid,integer,timestamptz,text,timestamptz)','EXECUTE')",(role,))
                self.assertEqual(q.fetchone()[0],role=='service_role')
            q.execute("SELECT provolatile,prosecdef FROM pg_proc WHERE oid='pending_approval_feed(uuid,integer,timestamptz,text,timestamptz)'::regprocedure")
            self.assertEqual(q.fetchone(),('s',True))

    def test_page_boundary_excludes_later_inserts_but_preserves_equal_timestamp_ties(self):
        self.seed('workflow',created_at='2026-01-01T11:00:00Z')
        self.seed('workflow')
        first = self.pending(limit=1)
        self.seed('milo',created_at='2099-01-01T00:00:00Z')
        second = self.pending(limit=1,cursor=first['next_cursor'])
        self.assertEqual(len(second['items']),1)
        self.assertIsNone(second['next_cursor'])
