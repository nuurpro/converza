"""Real PostgreSQL atomicity/concurrency gate. Requires isolated test_* DSN."""
import asyncio
import concurrent.futures
from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
import uuid

from lib.repository import SupabaseRepository
from services.milo.store import MiloStore
from services.sleyz.store import SleyzStore
from services.workflow.state import WorkflowConflict
import test_workflow_postgres as workflow_tests


@unittest.skipUnless(os.getenv('CONVERZA_WORKFLOW_TEST_DSN'), 'requires isolated PostgreSQL test database')
class MiloPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pg_supabase import PgSupabase
        workflow_tests.PostgresWorkflowTests.setUpClass()
        cls.client = PgSupabase(workflow_tests.DSN)
        cls.repo = SupabaseRepository(cls.client)
        cls.store = MiloStore(cls.repo)
        base = Path(__file__).resolve().parents[1] / 'migrations'
        with cls.client.connect() as c, c.cursor() as q:
            q.execute("SELECT to_regclass('sleyz_inbound')")
            if not q.fetchone()[0]:
                q.execute((base / '007_sleyz_inbound.sql').read_text())
            q.execute((base / '008_milo_campaigns.sql').read_text())
            q.execute((base / '010_consolidation.sql').read_text())
            q.execute((base / '013_milo_scope.sql').read_text())

    def setUp(self):
        self.org = str(uuid.uuid4())
        self.client.table('orgs').insert({'id': self.org}).execute()
        self.client.table('brand_passports').insert({'org_id': self.org, 'brand_name': 'Test'}).execute()

    def tearDown(self):
        # Existing workflow references are restrictive; clean in dependency order.
        with self.client.connect() as c, c.cursor() as q:
            q.execute('UPDATE drafts SET superseded_by=NULL WHERE org_id=%s', (self.org,))
            q.execute('DELETE FROM squad_messages WHERE org_id=%s', (self.org,))
            q.execute('DELETE FROM drafts WHERE org_id=%s', (self.org,))
            q.execute('DELETE FROM prospects WHERE org_id=%s', (self.org,))
            q.execute('DELETE FROM brand_passports WHERE org_id=%s', (self.org,))
            q.execute('DELETE FROM orgs WHERE id=%s', (self.org,))

    def run_async(self, awaitable):
        return asyncio.run(awaitable)

    def accept(self, **changes):
        return self.run_async(SleyzStore(self.repo).accept({**dict(org_id=self.org, platform='telegram', connection_id='biz',
            external_message_id='1', customer_id='42', text='Will it last?', received_at=datetime.now(timezone.utc).isoformat()), **changes}))

    def ready(self):
        campaign = self.run_async(self.store.enqueue(self.org, 'manual'))
        job = self.run_async(self.store.claim('generate'))[0]
        revision = self.client.table('memory_sources').select('revision').eq('org_id', self.org).eq('kind', 'passport').execute().data[0]['revision']
        artifact = {'brand_revision': revision, 'proof_references': [], 'video_script': [{'spoken_narration': 'Exact approved words', 'visual_broll_cues': 'Close up', 'on_screen_text': 'Look'}]}
        return self.run_async(self.store.complete_generation(job, artifact, {'passed': True, 'semantic_checked': True, 'checked_brand_revision': revision}))

    def test_capture_is_inbound_transactional_excludes_duplicates_and_simulations(self):
        accepted = self.accept()
        self.accept()
        self.accept(simulated=True, external_message_id='simulation')
        jobs = self.run_async(self.store.claim('extract', limit=100))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['payload']['inbound_id'], accepted['inbound_id'])
        item = {'objection_type': 'durability', 'topic': 'durability', 'product_id': None, 'buyer_text': 'last', 'span_start': 8, 'span_end': 12}
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.finish_extraction(jobs[0], [item, {**item, 'buyer_text': 'fake'}]))
        self.assertEqual(self.run_async(self.store.objections(self.org, '2000-01-01')), [])
        self.assertTrue(self.run_async(self.store.finish_extraction(jobs[0], [item, item])))
        self.assertEqual(len(self.run_async(self.store.objections(self.org, '2000-01-01'))), 1)

    def test_concurrent_approval_and_exactly_one_build_and_hitl_video(self):
        c = self.ready()
        def approve(_):
            return self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve'))
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            rows = list(pool.map(approve, range(8)))
        self.assertTrue(all(r == rows[0] for r in rows))
        jobs = self.run_async(self.store.claim('build', limit=100))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['payload']['video_script'], c['artifact']['video_script'])
        c = self.run_async(self.store.complete_build(jobs[0], {'video_url': 'https://example.test/video.mp4'}))
        d = self.run_async(self.repo.get_draft(c['result']['draft_id']))
        self.assertEqual(d['status'], 'AWAITING_HITL')
        self.assertEqual(d['agent_slug'], 'vea')
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.complete_build(jobs[0], {}))

    def test_atomic_auto_dedup_cooldown_and_tenant_boundary(self):
        def enqueue(_):
            return self.run_async(self.store.enqueue(self.org, 'spike', key='same-evidence', topic='durability'))
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            rows = list(pool.map(enqueue, range(8)))
        self.assertEqual(len({r['id'] for r in rows}), 1)
        self.assertIsNone(self.run_async(self.store.enqueue(self.org, 'spike', key='new-evidence', topic='durability')))
        self.assertEqual(self.run_async(self.store.enqueue(self.org, 'daily', key='same-evidence'))['id'], rows[0]['id'])
        self.assertIsNone(self.run_async(self.store.get_campaign(str(uuid.uuid4()), rows[0]['id'])))

    def test_stale_brand_proof_and_lease_are_rejected(self):
        c = self.ready()
        self.client.table('brand_passports').update({'brand_name': 'Changed'}).eq('org_id', self.org).execute()
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve'))
        self.run_async(self.store.enqueue(self.org, 'manual'))
        old = self.run_async(self.store.claim('generate'))[0]
        with self.client.connect() as conn, conn.cursor() as q:
            q.execute("UPDATE milo_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (old['id'],))
        new = self.run_async(self.store.claim('generate'))[0]
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.complete_generation(old, {}, {}))
        self.assertNotEqual(old['lease_token'], new['lease_token'])

    def test_concurrent_claim_permissions_and_backfill_idempotency(self):
        self.accept()
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            jobs = [j for batch in pool.map(lambda _: self.run_async(self.store.claim('extract')), range(4)) for j in batch]
        self.assertEqual(len(jobs), 1)
        with self.client.connect() as c, c.cursor() as q:
            for role in ('anon', 'authenticated', 'service_role'):
                q.execute("SELECT has_function_privilege(%s,'milo_store(text,jsonb)','EXECUTE')", (role,))
                self.assertEqual(q.fetchone()[0], role == 'service_role')
            q.execute((Path(__file__).resolve().parents[1] / 'migrations/008_milo_campaigns.sql').read_text())
            q.execute((Path(__file__).resolve().parents[1] / 'migrations/010_consolidation.sql').read_text())
            q.execute((Path(__file__).resolve().parents[1] / 'migrations/013_milo_scope.sql').read_text())
        self.assertEqual(len(self.run_async(self.store.jobs(self.org))), 1)

    def test_daily_limit_and_manual_idempotency_conflict(self):
        self.run_async(self.store.enqueue(self.org, 'daily', key='evidence-one'))
        self.assertIsNone(self.run_async(self.store.enqueue(self.org, 'daily', key='evidence-two')))
        self.run_async(self.store.enqueue(self.org, 'manual', prompt='One', key='manual'))
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.enqueue(self.org, 'manual', prompt='Two', key='manual'))

    def test_ambiguous_submission_receipt_and_submitted_recovery(self):
        c = self.ready()
        self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve'))
        j = self.run_async(self.store.claim('build'))[0]
        self.run_async(self.store.update_build(j, {'submission_state': 'submitting'}))
        self.run_async(self.store.fail(j, 'private provider response'))
        self.assertEqual(self.run_async(self.store.claim('build')), [])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.reconcile_build(str(uuid.uuid4()), j['id'], 'task'))
        self.run_async(self.store.reconcile_build(self.org, j['id'], 'task'))
        resumed = self.run_async(self.store.claim('build'))[0]
        self.assertEqual(resumed['payload']['provider_task_id'], 'task')
        self.assertEqual(resumed['payload']['submission_state'], 'submitted')
        self.assertEqual(resumed['payload']['video_script'], c['artifact']['video_script'])

    def test_generation_failure_exhaustion_and_crash_exhaustion(self):
        self.run_async(self.store.enqueue(self.org, 'manual'))
        for _ in range(3):
            j = self.run_async(self.store.claim('generate'))[0]
            self.run_async(self.store.fail(j, 'private token'))
            with self.client.connect() as c, c.cursor() as q:
                q.execute('UPDATE milo_jobs SET available_at=now() WHERE id=%s', (j['id'],))
        self.assertEqual(self.run_async(self.store.claim('generate')), [])
        self.assertNotIn('private', str(self.run_async(self.store.jobs(self.org))))
        self.run_async(self.store.retry(self.org, j['id']))
        j = self.run_async(self.store.claim('generate'))[0]
        with self.client.connect() as c, c.cursor() as q:
            q.execute("UPDATE milo_jobs SET attempts=3,lease_until=now()-interval '1 second' WHERE id=%s", (j['id'],))
        self.assertEqual(self.run_async(self.store.claim('generate')), [])
        self.assertEqual(self.run_async(self.store.get_campaign(self.org, j['campaign_id']))['status'], 'failed')

    def test_inbound_rollback_leaves_no_extraction_and_refresh_is_excluded(self):
        from psycopg2.extras import Json
        envelope = dict(org_id=self.org, platform='telegram', connection_id='biz', external_message_id='rollback',
            customer_id='42', text='Will it last?', received_at=datetime.now(timezone.utc).isoformat())
        with self.client.connect() as c, c.cursor() as q:
            q.execute('SELECT sleyz_accept_inbound(%s)', (Json(envelope),))
            c.rollback()
        self.assertEqual(self.run_async(self.store.jobs(self.org)), [])
        self.accept(external_message_id='1:refresh:one')
        self.assertEqual(self.run_async(self.store.claim('extract')), [])

    def test_proof_changed_or_forgotten_and_foreign_catalog_are_blocked(self):
        self.accept()
        j = self.run_async(self.store.claim('extract'))[0]
        item = dict(objection_type='durability', topic='durability', product_id=str(uuid.uuid4()), buyer_text='last', span_start=8, span_end=12)
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.finish_extraction(j, [item]))
        c = self.ready()
        source = self.client.table('memory_sources').select('*').eq('org_id', self.org).eq('kind', 'passport').execute().data[0]
        with self.client.connect() as conn, conn.cursor() as q:
            from psycopg2.extras import Json
            artifact = {**c['artifact'], 'proof_references': [{'source_id': source['id'], 'revision': source['revision'], 'quote': 'Fabricated claim'}]}
            q.execute('UPDATE milo_campaigns SET artifact=%s WHERE id=%s', (Json(artifact), c['id']))
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve'))

    def test_lease_renewal_is_fenced(self):
        self.run_async(self.store.enqueue(self.org, 'manual'))
        j = self.run_async(self.store.claim('generate'))[0]
        renewed = self.run_async(self.store.renew(j))
        self.assertGreaterEqual(renewed['lease_until'], j['lease_until'])
        with self.client.connect() as c, c.cursor() as q:
            q.execute("UPDATE milo_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (j['id'],))
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.renew(j))

    def test_expiring_evidence_cannot_retrigger_daily_or_spike(self):
        c = self.run_async(self.store.enqueue(self.org, 'spike', key='all', topic='durability', evidence_ids=['one', 'two']))
        with self.client.connect() as conn, conn.cursor() as q:
            q.execute("UPDATE milo_campaigns SET created_at=now()-interval '2 days' WHERE id=%s", (c['id'],))
        self.assertIsNone(self.run_async(self.store.enqueue(self.org, 'spike', key='expiry-changed-hash', topic='durability', evidence_ids=['two'])))
        self.assertIsNone(self.run_async(self.store.enqueue(self.org, 'daily', key='proof-changed-hash', topic='durability', evidence_ids=['two'])))
        c = self.run_async(self.store.enqueue(self.org, 'spike', key='new-id', topic='durability', evidence_ids=['two', 'three']))
        self.assertEqual(c['evidence_ids'], ['two', 'three'])

    def test_paid_submission_rechecks_approved_sources_and_generic_retry_needs_receipt(self):
        c = self.ready()
        self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve'))
        j = self.run_async(self.store.claim('build'))[0]
        self.client.table('brand_passports').update({'brand_name': 'Changed before paid submission'}).eq('org_id', self.org).execute()
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.update_build(j, {'submission_state': 'submission_started'}))
        # A distinct, fresh campaign can submit; an uncertain outcome requires a receipt.
        c = self.ready()
        self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve2'))
        j = self.run_async(self.store.claim('build'))[0]
        self.run_async(self.store.update_build(j, {'submission_state': 'submission_started'}))
        self.run_async(self.store.fail(j, 'Lost receipt'))
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.retry(self.org, j['id']))

    def test_paid_submission_blocks_changed_and_deleted_product_proof(self):
        from psycopg2.extras import Json
        product = self.client.table('brand_products').insert({'org_id': self.org, 'name': 'Bag', 'description': 'Reinforced stitching'}).execute().data[0]
        proof = self.client.table('memory_sources').select('*').eq('org_id', self.org).eq('kind', 'product').execute().data[0]
        c = self.ready()
        with self.client.connect() as conn, conn.cursor() as q:
            artifact = {**c['artifact'], 'proof_references': [{'source_id': proof['id'], 'revision': proof['revision'], 'quote': 'Reinforced stitching'}]}
            q.execute('UPDATE milo_campaigns SET artifact=%s WHERE id=%s', (Json(artifact), c['id']))
        self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve'))
        j = self.run_async(self.store.claim('build'))[0]
        self.client.table('brand_products').update({'description': 'Different materials'}).eq('id', product['id']).execute()
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.update_build(j, {'submission_state': 'submission_started'}))

        # Capture the fresh source revision then delete the product before submission.
        proof = self.client.table('memory_sources').select('*').eq('id', proof['id']).execute().data[0]
        with self.client.connect() as conn, conn.cursor() as q:
            artifact['proof_references'] = [{'source_id': proof['id'], 'revision': proof['revision'], 'quote': 'Different materials'}]
            q.execute('UPDATE milo_campaigns SET artifact=%s WHERE id=%s', (Json(artifact), c['id']))
        self.client.table('brand_products').update({'deleted_at': datetime.now(timezone.utc).isoformat()}).eq('id', product['id']).execute()
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.update_build(j, {'submission_state': 'submission_started'}))

    def test_cooldown_is_shared_across_daily_and_spike(self):
        self.run_async(self.store.enqueue(self.org, 'spike', key='first', topic='durability', evidence_ids=['one']))
        self.assertIsNone(self.run_async(self.store.enqueue(self.org, 'daily', key='next', topic='durability', evidence_ids=['one', 'two'])))
        self.run_async(self.store.enqueue(self.org, 'daily', key='daily-other-topic', topic='price', evidence_ids=['three']))
        self.assertIsNone(self.run_async(self.store.enqueue(self.org, 'spike', key='after-daily', topic='price', evidence_ids=['three', 'four'])))

    def test_provider_failure_retry_creates_new_attempt_idempotently(self):
        c = self.ready()
        self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve'))
        j = self.run_async(self.store.claim('build'))[0]
        self.run_async(self.store.update_build(j, {'provider_task_id': 'task-one', 'submission_state': 'provider_failed'}))
        self.run_async(self.store.fail(j, 'ProviderRenderFailed'))
        self.assertEqual(self.run_async(self.store.jobs(self.org))[-1]['status'], 'failed')
        def retry(_): return self.run_async(self.store.retry(self.org, j['id'], key='retry-once'))
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            results = list(pool.map(retry, range(8)))
        self.assertTrue(all(r == results[0] for r in results))
        payload = results[0]['payload']
        self.assertEqual(payload['provider_attempt'], 2)
        self.assertEqual(payload['submission_state'], 'not_submitted')
        self.assertFalse(payload.get('provider_task_id'))
        self.assertEqual(payload['provider_attempts'][0]['provider_task_id'], 'task-one')
        next_job = self.run_async(self.store.claim('build'))[0]
        self.assertEqual(next_job['id'], j['id'])
        self.assertEqual(next_job['payload']['video_script'], c['artifact']['video_script'])
        self.assertEqual(self.run_async(self.store.retry(self.org, j['id'], key='retry-once')), results[0])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.reconcile_build(self.org, j['id'], 'other', key='retry-once'))

    def test_timeout_keeps_existing_provider_task_and_receipt_replay_is_idempotent(self):
        c = self.ready()
        self.run_async(self.store.decide_script(self.org, c['id'], 'approve', c['revision'], 'approve'))
        j = self.run_async(self.store.claim('build'))[0]
        self.run_async(self.store.update_build(j, {'provider_task_id': 'live-task', 'submission_state': 'submitted'}))
        with self.client.connect() as conn, conn.cursor() as q:
            q.execute('UPDATE milo_jobs SET attempts=3 WHERE id=%s', (j['id'],))
        self.run_async(self.store.fail(j, 'TimeoutError'))
        retried = self.run_async(self.store.retry(self.org, j['id'], key='poll-again'))
        self.assertEqual(retried['payload']['provider_task_id'], 'live-task')
        self.assertEqual(retried['payload'].get('provider_attempt', 1), 1)
        next_job = self.run_async(self.store.claim('build'))[0]
        self.run_async(self.store.update_build(next_job, {'provider_task_id': None, 'submission_state': 'ambiguous'}))
        self.run_async(self.store.fail(next_job, 'SubmissionUncertain'))
        result = self.run_async(self.store.reconcile_build(self.org, j['id'], 'receipt-task', key='receipt'))
        self.assertEqual(self.run_async(self.store.reconcile_build(self.org, j['id'], 'receipt-task', key='receipt')), result)
        live = self.run_async(self.store.claim('build'))[0]
        self.assertEqual(self.run_async(self.store.replay_reconcile(self.org, j['id'], 'receipt-task', 'receipt')), result)
        self.assertEqual(self.run_async(self.store.jobs(self.org))[-1]['lease_token'], live['lease_token'])
        self.assertIsNone(self.run_async(self.store.replay_reconcile(self.org, j['id'], 'receipt-task', 'unused')))
        self.assertIsNone(self.run_async(self.store.replay_reconcile(str(uuid.uuid4()), j['id'], 'receipt-task', 'receipt')))
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.reconcile_build(self.org, j['id'], 'changed-task', key='receipt'))
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.replay_reconcile(self.org, j['id'], 'changed-task', 'receipt'))
