"""Selected generation scope parity in an explicitly isolated test database."""
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from services.vea.store import VeaStore, prepare_build
from services.workflow.state import WorkflowConflict
import test_vea_postgres as vea_tests
from test_vea_storage import catalog_asset


@unittest.skipUnless(os.getenv('CONVERZA_WORKFLOW_TEST_DSN'), 'requires isolated PostgreSQL test database')
class ConsolidationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        vea_tests.VeaPostgresTests.setUpClass()
        cls.client = vea_tests.VeaPostgresTests.client
        cls.repo = vea_tests.VeaPostgresTests.repo
        cls.store = vea_tests.VeaPostgresTests.store
        migration = Path(__file__).resolve().parents[1] / 'migrations/010_consolidation.sql'
        if migration.exists():
            with cls.client.connect() as conn, conn.cursor() as q:
                q.execute(migration.read_text(encoding='utf-8'))
                q.execute((migration.parent / '013_milo_scope.sql').read_text(encoding='utf-8'))

    setUp = vea_tests.VeaPostgresTests.setUp
    tearDown = vea_tests.VeaPostgresTests.tearDown
    ready = vea_tests.VeaPostgresTests.ready
    run_async = vea_tests.VeaPostgresTests.run_async
    result = vea_tests.VeaPostgresTests.result

    def product(self):
        return self.client.table('brand_products').insert({'org_id': self.org,
            'name': 'Selected initiative'}).execute().data[0]['id']

    def test_manual_selected_product_reaches_default_and_alternate_builds(self):
        template = self.ready()
        campaign = self.run_async(self.store.enqueue(self.org, 'manual', key='scope'))
        job = self.run_async(self.store.claim('generate'))[0]
        product = self.product()
        scope = {'product_id': product, 'topic': 'durability'}
        current = self.run_async(self.store.complete_generation(job, template['artifact'], template['compliance'], selected_scope=scope))
        self.assertEqual((current['product_id'], current['topic']), (product, 'durability'))
        self.assertEqual(self.run_async(self.store.enqueue(self.org, 'manual', key='scope')), current)
        approved = self.run_async(self.store.decide_script(self.org, campaign['id'], 'approve', current['revision'], 'approve-scope'))
        replay = self.run_async(self.store.decide_script(self.org, campaign['id'], 'approve', current['revision'], 'approve-scope'))
        self.assertEqual(approved, replay)
        job = self.run_async(prepare_build(self.run_async(self.store.claim('build'))[0], self.store))
        self.assertEqual(job['payload']['vea_config']['product_id'], product)
        vea = VeaStore(self.repo)
        default = self.run_async(vea.list_variants(self.org))[0]
        self.assertEqual(default['product_id'], product)
        self.run_async(self.store.complete_build(job, self.result(approved, default)))
        catalog = AsyncMock(return_value={'assets': [
            catalog_asset(self.org)]})
        with patch('services.vea.store.fetch_renderer', catalog):
            self.run_async(vea.swap(self.org, default['id'], 1, 'scene-0-cut-0', 'replacement', 'scope-swap'))
        catalog.assert_awaited_once_with('assets', {'org_id': self.org, 'selection':'manual', 'language': 'en'})
        variant = self.run_async(vea.create_variant(self.org, campaign['id'], approved['revision'], 'editorial_showcase', 'alternate'))
        self.assertEqual(variant['product_id'], product)
        queued = next(j for j in self.run_async(self.store.jobs(self.org)) if j['id'] == variant['job_id'])
        self.assertEqual(queued['payload']['vea_config']['product_id'], product)
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.complete_generation(job, {}, {}, selected_scope=scope))

    def test_scope_conflict_is_atomic_and_sql_does_not_infer_from_copy(self):
        product = self.product()
        self.run_async(self.store.enqueue(self.org, 'manual', topic='durability', product_id=product))
        job = self.run_async(self.store.claim('generate'))[0]
        for scope in ({'product_id': product, 'topic': 'price'}, {'product_id': 'different', 'topic': 'durability'}):
            with self.subTest(scope=scope), self.assertRaises(WorkflowConflict):
                self.run_async(self.store.complete_generation(job, {}, {}, selected_scope=scope))
            campaign = self.run_async(self.store.get_campaign(self.org, job['campaign_id']))
            self.assertEqual((campaign['revision'], campaign['product_id'], campaign['topic']), (1, product, 'durability'))
        current = self.run_async(self.store.complete_generation(job, {'product_id': 'model-guess'}, {'passed': False}))
        self.assertEqual(current['product_id'], product)

    def test_generated_rpc_rejects_malformed_scope_before_any_write(self):
        self.run_async(self.store.enqueue(self.org, 'manual'))
        job = self.run_async(self.store.claim('generate'))[0]
        for scope in ('guess', {}, {'topic': 'trust', 'product_id': 42},
                      {'topic': 'invented', 'product_id': None}, {'topic': 'trust', 'product_id': None, 'extra': True}):
            with self.subTest(scope=scope), self.assertRaises(WorkflowConflict):
                self.run_async(self.store._rpc('generated', job=job['id'], token=job['lease_token'],
                    artifact={}, compliance={}, missing=[], selected_scope=scope))
            self.assertEqual(self.run_async(self.store.get_campaign(self.org, job['campaign_id']))['revision'], 1)
        current = self.run_async(self.store.complete_generation(job, {}, {'passed': False},
            selected_scope={'topic': 'trust', 'product_id': None}))
        self.assertEqual((current['product_id'], current['topic']), (None, 'trust'))

    def test_migration_reapply_preserves_service_only_permissions(self):
        migration = Path(__file__).resolve().parents[1] / 'migrations/013_milo_scope.sql'
        self.assertTrue(migration.exists())
        with self.client.connect() as conn, conn.cursor() as q:
            q.execute(migration.read_text(encoding='utf-8'))
            for role in ('anon', 'authenticated', 'service_role'):
                q.execute("SELECT has_function_privilege(%s,'milo_store(text,jsonb)','EXECUTE')", (role,))
                self.assertEqual(q.fetchone()[0], role == 'service_role')
