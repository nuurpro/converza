"""Real SQL scope checks. Runs only on an explicitly disposable test database."""
import concurrent.futures
import os
from pathlib import Path
import unittest
import uuid

import test_milo_postgres as base
from services.workflow.state import WorkflowConflict


@unittest.skipUnless(os.getenv('CONVERZA_WORKFLOW_TEST_DSN'), 'requires isolated PostgreSQL test database')
class ScopePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.MiloPostgresTests.setUpClass()
        cls.client, cls.repo, cls.store = (base.MiloPostgresTests.client,
            base.MiloPostgresTests.repo, base.MiloPostgresTests.store)
        migration = Path(__file__).resolve().parents[1] / 'migrations/013_milo_scope.sql'
        if migration.exists():
            with cls.client.connect() as conn, conn.cursor() as q:
                q.execute(migration.read_text(encoding='utf-8'))

    setUp = base.MiloPostgresTests.setUp
    tearDown = base.MiloPostgresTests.tearDown
    run_async = base.MiloPostgresTests.run_async
    ready = base.MiloPostgresTests.ready

    def product(self, org=None, **values):
        return self.client.table('brand_products').insert(dict(org_id=org or self.org,
            name='Festival initiative', **values)).execute().data[0]['id']

    def test_invalid_explicit_scope_is_rejected_atomically(self):
        deleted = self.product(deleted_at='2026-10-19T00:00:00Z')
        other = str(uuid.uuid4())
        self.client.table('orgs').insert({'id': other}).execute()
        foreign = self.product(other)
        try:
            for product in (str(uuid.uuid4()), deleted, foreign, '', ' '):
                with self.subTest(product=product), self.assertRaises(WorkflowConflict):
                    self.run_async(self.store.enqueue(self.org, 'manual', product_id=product))
                self.assertEqual(self.run_async(self.store.list_campaigns(self.org)), [])
                self.assertEqual(self.run_async(self.store.jobs(self.org)), [])
        finally:
            self.client.table('orgs').delete().eq('id', other).execute()

    def test_concurrent_creation_and_scope_idempotency(self):
        product = self.product()
        def enqueue(_):
            return self.run_async(self.store.enqueue(self.org, 'manual', key='same', product_id=product))
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            rows = list(pool.map(enqueue, range(8)))
        self.assertEqual(len({row['id'] for row in rows}), 1)
        for changed in (self.product(), None):
            with self.subTest(changed=changed), self.assertRaises(WorkflowConflict):
                self.run_async(self.store.enqueue(self.org, 'manual', key='same', product_id=changed))
        self.assertEqual(len(self.run_async(self.store.jobs(self.org))), 1)

    def test_generation_cannot_persist_unknown_product(self):
        self.run_async(self.store.enqueue(self.org, 'manual'))
        job = self.run_async(self.store.claim('generate'))[0]
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.complete_generation(job, {}, {},
                selected_scope={'product_id': str(uuid.uuid4()), 'topic': 'trust'}))
        row = self.run_async(self.store.get_campaign(self.org, job['campaign_id']))
        self.assertEqual((row['revision'], row['product_id']), (1, None))

    def test_approved_build_payload_and_retry_keep_selection(self):
        product = self.product()
        self.run_async(self.store.enqueue(self.org, 'manual', product_id=product))
        job = self.run_async(self.store.claim('generate'))[0]
        revision = self.client.table('memory_sources').select('revision').eq('org_id', self.org).eq('kind', 'passport').execute().data[0]['revision']
        row = self.run_async(self.store.complete_generation(job, {'brand_revision': revision,
            'proof_references': [], 'video_script': []}, {'passed': True, 'semantic_checked': True,
            'checked_brand_revision': revision}, selected_scope={'product_id': product, 'topic': 'trust'}))
        self.run_async(self.store.decide_script(self.org, row['id'], 'approve', row['revision'], 'approve'))
        build = self.run_async(self.store.claim('build'))[0]
        self.assertEqual(build['payload']['product_id'], product)
        self.run_async(self.store.update_build(build, {'submission_state': 'provider_failed'}))
        self.run_async(self.store.fail(build, 'ProviderRenderFailed'))
        retried = self.run_async(self.store.retry(self.org, build['id'], 'retry'))
        self.assertEqual((retried['id'], retried['payload']['product_id']), (build['id'], product))

    def test_migration_is_idempotent_and_service_only(self):
        migration = Path(__file__).resolve().parents[1] / 'migrations/013_milo_scope.sql'
        self.assertTrue(migration.exists())
        with self.client.connect() as conn, conn.cursor() as q:
            q.execute(migration.read_text(encoding='utf-8'))
            for function in ('milo_store(text,jsonb)', 'milo_assert_product(uuid,text)'):
                for role in ('anon', 'authenticated', 'service_role'):
                    q.execute('SELECT has_function_privilege(%s,%s,\'EXECUTE\')', (role, function))
                    self.assertEqual(q.fetchone()[0], role == 'service_role')
