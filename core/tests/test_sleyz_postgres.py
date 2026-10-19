"""Real PostgreSQL inbox/worker/learning gate, enabled by an explicit test DSN."""
import asyncio
import concurrent.futures
from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
import uuid

from lib.repository import SupabaseRepository
from services.sleyz.store import SleyzStore
from services.workflow.state import WorkflowConflict
import test_workflow_postgres as workflow_tests


@unittest.skipUnless(os.getenv('CONVERZA_WORKFLOW_TEST_DSN'), 'requires isolated PostgreSQL test database')
class SleyzPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_workflow_postgres
        from pg_supabase import PgSupabase
        workflow_tests.PostgresWorkflowTests.setUpClass()
        cls.client = PgSupabase(test_workflow_postgres.DSN)
        cls.repo = SupabaseRepository(cls.client)
        cls.store = SleyzStore(cls.repo)
        with cls.client.connect() as c, c.cursor() as q:
            q.execute("SELECT to_regclass('sleyz_inbound')")
            if not q.fetchone()[0]:
                q.execute((Path(__file__).resolve().parents[1] / 'migrations/007_sleyz_inbound.sql').read_text())

    def setUp(self):
        self.org = str(uuid.uuid4())
        self.client.table('orgs').insert({'id': self.org}).execute()
        self.envelope = dict(org_id=self.org, platform='telegram', connection_id='business', external_message_id='1',
            customer_id='42', customer_handle='buyer', text='Too expensive', received_at=datetime.now(timezone.utc).isoformat(), simulated=False,
            tg_chat_id=42, business_connection_id='business')

    def tearDown(self):
        self.client.table('squad_messages').delete().eq('org_id', self.org).execute()
        self.client.table('drafts').delete().eq('org_id', self.org).execute()
        self.client.table('prospects').delete().eq('org_id', self.org).execute()
        self.client.table('orgs').delete().eq('id', self.org).execute()

    def run_async(self, awaitable):
        return asyncio.run(awaitable)

    def generated(self, **changes):
        accepted = self.run_async(self.store.accept({**self.envelope, **changes}))
        job = self.run_async(self.store.claim())[0]
        draft = self.run_async(self.store.ready(job, {'schema_version':1, 'draft_reply':'Original reply'}))
        return accepted, job, draft

    def test_concurrent_accept_deduplicates_and_worker_fences_expired_lease(self):
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: self.run_async(self.store.accept(self.envelope)), range(8)))
        self.assertEqual(len({r['draft_id'] for r in results}), 1)
        old = self.run_async(self.store.claim())[0]
        with self.client.connect() as c, c.cursor() as q:
            q.execute("UPDATE sleyz_inbound SET lease_until=now()-interval '1 second' WHERE id=%s", (old['id'],))
        new = self.run_async(self.store.claim())[0]
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.ready(old, {'draft_reply':'Stale'}))
        draft = self.run_async(self.store.ready(new, {'draft_reply':'Fresh'}))
        self.assertEqual(draft['sleyz_artifact']['draft_reply'], 'Fresh')
        snapshot = self.run_async(self.repo.snapshot(self.org))
        self.assertEqual(snapshot['drafts'][0]['status'], 'AWAITING_HITL')
        self.assertEqual(len(snapshot['messages']), 1)

    def test_approved_edit_learning_is_transactional_and_provenance_retained(self):
        _, _, d = self.generated()
        d = self.run_async(self.repo.transition_draft(self.org, d['id'], 'edit', d['revision'], 'edit', edited_content='Approved reply'))
        self.assertEqual(d['learning_status'], 'pending')
        job = self.run_async(self.store.claim_learning())[0]
        self.assertEqual(job['original_content'], 'Original reply')
        self.assertGreater(self.run_async(self.repo.get_draft(d['id']))['revision'],d['revision'])
        correction = {'rule':'Be concise', 'rule_type':'style', 'supporting_spans':[{'text':'Approved', 'start':0, 'end':8}]}
        self.assertTrue(self.run_async(self.store.complete_learning(job, correction)))
        source = self.client.table('memory_sources').select('*').eq('org_id', self.org).eq('kind','correction').execute().data[0]
        self.assertEqual(source['metadata']['approved_revision'], d['revision'])
        self.assertEqual(source['metadata']['priority'], 2)
        self.assertEqual(source['atoms'][0]['text'], 'Be concise')
        self.assertFalse(self.run_async(self.store.complete_learning(job, correction)))
        self.assertTrue(self.client.rpc('memory_forget_source', {'p_org':self.org,'p_source':source['id']}).execute().data)

    def test_refresh_and_simulation_prevent_customer_delivery(self):
        _, _, d = self.generated(simulated=True)
        d = self.run_async(self.repo.transition_draft(self.org, d['id'], 'edit', d['revision'], 'edit', edited_content='Edited'))
        self.assertEqual(self.run_async(self.store.claim_learning()), [])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.repo.transition_draft(self.org,d['id'],'begin_delivery',d['revision'],'send',receipt={'attempt_id':'a'}))
        result = self.run_async(self.store.refresh(self.org,d['id'],d['revision'],'refresh'))
        self.assertEqual(result,self.run_async(self.store.refresh(self.org,d['id'],d['revision'],'refresh')))
        self.assertEqual(self.run_async(self.repo.get_draft(d['id']))['superseded_by'],result['draft_id'])

    def test_telemetry_validates_exact_span_and_rpc_permissions(self):
        _, job, _ = self.generated()
        objections = [{'type':'price','text':'Too expensive','span':[0,13]}]
        self.run_async(self.store.telemetry(job, objections))
        self.run_async(self.store.telemetry(job, objections))
        self.assertEqual(len(self.client.table('objection_telemetry').select('*').eq('org_id',self.org).execute().data),1)
        with self.client.connect() as c, c.cursor() as q:
            for role in ('anon','authenticated','service_role'):
                q.execute("SELECT has_function_privilege(%s,'sleyz_accept_inbound(jsonb)','EXECUTE')",(role,))
                self.assertEqual(q.fetchone()[0],role=='service_role')

    def test_failure_exhaustion_and_crash_exhaustion_are_persistent(self):
        self.run_async(self.store.accept(self.envelope))
        for _ in range(3):
            job = self.run_async(self.store.claim())[0]
            self.assertTrue(self.run_async(self.store.fail(job,'sensitive message token')))
            with self.client.connect() as c, c.cursor() as q:
                q.execute("UPDATE sleyz_inbound SET available_at=now() WHERE id=%s", (job['id'],))
        self.assertEqual(self.run_async(self.store.claim()),[])
        d = self.run_async(self.repo.get_draft(job['draft_id']))
        self.assertEqual(d['generation_status'],'failed')
        self.assertNotIn('sensitive',d['generation_error'])
        result = self.run_async(self.store.retry_generation(self.org,d['id'],d['revision'],'retry'))
        self.assertEqual(result['id'],d['id'])
        self.assertEqual(result['generation_status'],'pending')
        self.assertEqual(self.run_async(self.store.retry_generation(self.org,d['id'],d['revision'],'retry')),result)
        self.assertEqual(self.run_async(self.store.claim())[0]['attempts'],1)

    def test_concurrent_workers_claim_one_job_and_crash_exhaustion_is_visible(self):
        accepted = self.run_async(self.store.accept(self.envelope))
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            batches = list(pool.map(lambda _:self.run_async(self.store.claim()),range(4)))
        jobs = [job for batch in batches for job in batch]
        self.assertEqual(len(jobs),1)
        with self.client.connect() as c, c.cursor() as q:
            q.execute("UPDATE sleyz_inbound SET attempts=3,lease_until=now()-interval '1 second' WHERE id=%s",(accepted['inbound_id'],))
        self.assertEqual(self.run_async(self.store.claim()),[])
        draft = self.run_async(self.repo.get_draft(accepted['draft_id']))
        self.assertEqual(draft['generation_status'],'failed')
        self.assertTrue(draft['generation_error'])

    def test_edited_approval_rollback_does_not_leave_learning_job(self):
        _, _, d = self.generated()
        with self.client.connect() as c:
            with c.cursor() as q:
                q.execute("SELECT workflow_transition(%s,%s,'edit',%s,'rolled-back','Changed',NULL,NULL)",(self.org,d['id'],d['revision']))
            c.rollback()
        self.assertEqual(self.run_async(self.store.claim_learning()),[])
        self.assertEqual(self.run_async(self.repo.get_draft(d['id']))['status'],'AWAITING_HITL')

    def test_learning_retries_preserve_approved_snapshot_and_skipped_status(self):
        _, _, d = self.generated()
        d = self.run_async(self.repo.transition_draft(self.org,d['id'],'edit',d['revision'],'edit',edited_content='Changed'))
        for _ in range(3):
            job = self.run_async(self.store.claim_learning())[0]
            self.assertEqual(job['approved_revision'],d['revision'])
            self.run_async(self.store.fail_learning(job,'buyer secret token'))
            with self.client.connect() as c, c.cursor() as q:
                q.execute("UPDATE sleyz_learning_jobs SET available_at=now() WHERE id=%s",(job['id'],))
        self.assertEqual(self.run_async(self.store.claim_learning()),[])
        failed = self.run_async(self.repo.get_draft(d['id']))
        self.assertEqual(failed['learning_status'],'failed')
        self.assertNotIn('secret',failed['learning_error'])
        self.assertEqual(failed['status'],'EDITED')
        self.run_async(self.store.retry_learning(self.org,d['id']))
        job = self.run_async(self.store.claim_learning())[0]
        self.assertTrue(self.run_async(self.store.complete_learning(job,None)))
        self.assertEqual(self.run_async(self.repo.get_draft(d['id']))['learning_status'],'skipped')

    def test_catalog_constraints_keep_active_skus_unique_and_allow_unknown_stock(self):
        product = dict(org_id=self.org,name='Product',sku='ONE',stock_count=None,checkout_url_template='https://store.example/{sku}?quantity={quantity}')
        first = self.client.table('brand_products').insert(product).execute().data[0]
        with self.assertRaises(Exception):
            self.client.table('brand_products').insert(product).execute()
        with self.assertRaises(Exception):
            self.client.table('brand_products').update({'stock_count':-1}).eq('id',first['id']).execute()
        self.client.table('brand_products').update({'deleted_at':datetime.now(timezone.utc).isoformat()}).eq('id',first['id']).execute()
        second = self.client.table('brand_products').insert(product).execute().data[0]
        self.assertNotEqual(first['id'],second['id'])

    def test_directmode_inbound_clears_prior_business_destination(self):
        first = self.run_async(self.store.accept(self.envelope))
        second = self.run_async(self.store.accept({**self.envelope,'connection_id':'direct','external_message_id':'2','business_connection_id':None}))
        d1 = self.run_async(self.repo.get_draft(first['draft_id']))
        d2 = self.run_async(self.repo.get_draft(second['draft_id']))
        self.assertEqual(d1['prospect_id'],d2['prospect_id'])
        prospect = self.client.table('prospects').select('*').eq('id',d2['prospect_id']).execute().data[0]
        self.assertIsNone(prospect['business_connection_id'])

    def test_service_rpc_rejects_missing_platform(self):
        envelope = dict(self.envelope)
        del envelope['platform']
        with self.assertRaises(Exception):
            self.client.rpc('sleyz_accept_inbound',{'p_envelope':envelope}).execute()
