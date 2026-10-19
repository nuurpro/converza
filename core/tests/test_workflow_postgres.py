"""Optional real-PostgreSQL gate. Only runs against an explicit test_* database.

CONVERZA_WORKFLOW_TEST_DSN='host=127.0.0.1 port=55439 user=postgres dbname=test_converza_workflow'
python -m unittest discover -s tests -p test_workflow_postgres.py
"""
import concurrent.futures
import os
from pathlib import Path
import threading
import unittest
import uuid

DSN = os.getenv('CONVERZA_WORKFLOW_TEST_DSN')


@unittest.skipUnless(DSN, 'requires explicit isolated PostgreSQL test database')
class PostgresWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        cls.connect = staticmethod(lambda: psycopg2.connect(DSN))
        with cls.connect() as c:
            with c.cursor() as q:
                q.execute('SELECT current_database()')
                if not q.fetchone()[0].startswith('test_'):
                    raise RuntimeError('Workflow SQL tests require a test_* database')
                q.execute("""
                DO $$ BEGIN CREATE ROLE service_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                CREATE EXTENSION IF NOT EXISTS pgcrypto;
                CREATE TABLE IF NOT EXISTS orgs(id uuid PRIMARY KEY DEFAULT gen_random_uuid());
                CREATE TABLE IF NOT EXISTS brand_passports(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid REFERENCES orgs(id),brand_name text,updated_at timestamptz DEFAULT now());
                CREATE TABLE IF NOT EXISTS prospects(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid REFERENCES orgs(id));
                CREATE TABLE IF NOT EXISTS drafts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
                prospect_id uuid,inbound_text text,draft_content text,final_content text,status text DEFAULT 'pending',created_at timestamptz DEFAULT now(),decided_at timestamptz);
                """)
                base = Path(__file__).resolve().parents[1] / 'migrations'
                q.execute("SELECT to_regclass('agent_runs')")
                if not q.fetchone()[0]:
                    q.execute((base / '001_agent_switchboard.sql').read_text(encoding='utf-8'))
                q.execute("SELECT to_regclass('memory_sources')")
                if not q.fetchone()[0]:
                    q.execute((base / '004_brand_memory.sql').read_text(encoding='utf-8'))
                q.execute("SELECT to_regclass('workflow_events')")
                if not q.fetchone()[0]:
                    q.execute((base / '005_hitl_events.sql').read_text(encoding='utf-8'))

    def setUp(self):
        self.org = str(uuid.uuid4())
        self.db = self.connect()
        self.db.autocommit = True
        self.q = self.db.cursor()
        self.q.execute('INSERT INTO orgs(id) VALUES(%s)', (self.org,))

    def tearDown(self):
        self.q.execute('DELETE FROM prospects WHERE org_id=%s',(self.org,))
        self.q.execute('DELETE FROM orgs WHERE id=%s',(self.org,))
        self.db.close()

    def draft(self):
        prospect = str(uuid.uuid4())
        self.q.execute('INSERT INTO prospects(id,org_id) VALUES(%s,%s)',(prospect,self.org))
        self.q.execute("INSERT INTO drafts(org_id,agent_slug,prospect_id,inbound_text,draft_content) VALUES(%s,'sleyz',%s,'Exact objection','') RETURNING to_jsonb(drafts.*)",(self.org,prospect))
        return self.q.fetchone()[0]

    def transition(self, draft, action, *, content=None, receipt=None, key=None, connection=None):
        from psycopg2.extras import Json
        q = connection.cursor() if connection else self.q
        q.execute('SELECT workflow_transition(%s,%s,%s,%s,%s,%s,%s,%s)',
            (self.org,draft['id'],action,draft['revision'],key or str(uuid.uuid4()),content,Json(receipt) if receipt else None,None))
        return q.fetchone()[0]

    def test_cas_and_duplicate_receipt_and_resolution_memory(self):
        d = self.transition(self.draft(),'ready',content='Exact final answer')
        d = self.transition(d,'edit',content='Exact final answer',key='edit')
        d = self.transition(d,'begin_delivery',receipt={'attempt_id':'a'})
        receipt = {'channel':'telegram','message_id':7,'attempt_id':'a'}
        published = self.transition(d,'publish',receipt=receipt,key='receipt')
        self.assertEqual(self.transition(d,'publish',receipt=receipt,key='receipt'),published)
        self.q.execute("SELECT count(*) FROM memory_sources WHERE org_id=%s AND kind='objection'",(self.org,))
        self.assertEqual(self.q.fetchone()[0],0)
        resolved = self.transition(published,'resolve')
        self.assertTrue(resolved['resolved_at'])
        self.q.execute("SELECT metadata FROM memory_sources WHERE org_id=%s AND kind='objection'",(self.org,))
        self.assertEqual(self.q.fetchone()[0]['inbound_text'],'Exact objection')

    def test_concurrent_decisions_have_one_winner(self):
        d = self.transition(self.draft(),'ready',content='Answer')
        barrier = threading.Barrier(2)
        def decide(action):
            with self.connect() as c:
                barrier.wait()
                try:
                    return self.transition(d,action,connection=c)['status']
                except Exception as exc:
                    self.assertIn('workflow_conflict',str(exc))
                    return 'conflict'
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(decide,['approve','reject']))
        self.assertEqual(results.count('conflict'),1)

    def test_rollback_does_not_leave_cursor_gap(self):
        c = self.connect()
        q = c.cursor()
        q.execute("INSERT INTO squad_messages(org_id,sender_slug,content) VALUES(%s,'owner','rolled back')",(self.org,))
        c.rollback()
        c.close()
        self.q.execute("INSERT INTO squad_messages(org_id,sender_slug,content) VALUES(%s,'owner','committed')",(self.org,))
        self.q.execute('SELECT workflow_snapshot(%s)',(self.org,))
        snapshot = self.q.fetchone()[0]
        self.assertEqual(snapshot['cursor'],1)
        self.assertEqual(len(snapshot['messages']),1)

    def test_snapshot_remains_consistent_during_concurrent_commits(self):
        def write():
            with self.connect() as c:
                c.autocommit = True
                with c.cursor() as q:
                    for _ in range(20):
                        q.execute("INSERT INTO squad_messages(org_id,sender_slug,content) VALUES(%s,'owner','committed')",(self.org,))
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            future = pool.submit(write)
            for _ in range(20):
                self.q.execute('SELECT workflow_snapshot(%s)',(self.org,))
                snapshot = self.q.fetchone()[0]
                self.assertEqual(snapshot['cursor'],len(snapshot['messages']))
            future.result()
        self.q.execute('SELECT workflow_read_events(%s,0,1000)',(self.org,))
        self.assertEqual([e['id'] for e in self.q.fetchone()[0]],list(range(1,21)))

    def test_decision_run_message_and_events_rollback_together(self):
        d = self.draft()
        self.q.execute("INSERT INTO agent_runs(org_id,agent_slug,triggered_by,input_text,status) VALUES(%s,'sleyz','owner','review','awaiting_hitl') RETURNING id",(self.org,))
        run = self.q.fetchone()[0]
        self.q.execute("INSERT INTO squad_messages(org_id,sender_slug,content,related_run_id,hitl_draft_id) VALUES(%s,'sleyz','Review',%s,%s)",(self.org,run,d['id']))
        d = self.transition(d,'ready',content='Answer')
        c = self.connect()
        self.transition(d,'approve',connection=c)
        c.rollback()
        c.close()
        self.q.execute('SELECT status FROM drafts WHERE id=%s',(d['id'],))
        self.assertEqual(self.q.fetchone()[0],'AWAITING_HITL')
        self.q.execute('SELECT status FROM agent_runs WHERE id=%s',(run,))
        self.assertEqual(self.q.fetchone()[0],'awaiting_hitl')
        d = self.transition(d,'approve')
        self.q.execute('SELECT workflow_snapshot(%s)',(self.org,))
        snapshot = self.q.fetchone()[0]
        self.assertEqual(snapshot['cursor'],5)
        self.assertEqual(len(snapshot['messages']),2)
        self.q.execute('SELECT status FROM agent_runs WHERE id=%s',(run,))
        self.assertEqual(self.q.fetchone()[0],'completed')

    def test_rpc_and_events_require_service_role(self):
        for role in ('anon','authenticated','service_role'):
            self.q.execute("SELECT has_function_privilege(%s,'workflow_transition(uuid,uuid,text,bigint,text,text,jsonb,text)','EXECUTE')",(role,))
            self.assertEqual(self.q.fetchone()[0],role=='service_role')

    def test_delivery_failure_rejection_and_wrong_org_are_guarded_in_database(self):
        d = self.transition(self.draft(),'ready',content='Answer')
        rejected = self.transition(d,'reject')
        with self.assertRaisesRegex(Exception,'workflow_conflict'):
            self.transition(rejected,'approve')
        d = self.transition(self.draft(),'ready',content='Answer')
        approved = self.transition(d,'approve')
        failed = self.transition(approved,'delivery_failed')
        self.assertEqual(failed['status'],'APPROVED')
        with self.assertRaisesRegex(Exception,'workflow_conflict'):
            self.transition(failed,'resolve')
        with self.assertRaisesRegex(Exception,'workflow_conflict'):
            self.transition(failed,'publish',receipt={'channel':'telegram','message_id':1,'attempt_id':'forged'})
