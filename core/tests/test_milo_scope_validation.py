"""Canonical product identity is reserved before any generation work is queued."""
from copy import deepcopy
import unittest

from lib.repository import InMemoryRepository
from services.milo.store import MiloStore
from services.workflow.state import WorkflowConflict


class ScopeValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = InMemoryRepository()
        self.repo.brand_products = [dict(id='initiative', org_id='org'),
            dict(id='other', org_id='org'), dict(id='foreign', org_id='elsewhere'),
            dict(id='deleted', org_id='org', deleted_at='2026-10-19T00:00:00Z')]
        self.store = MiloStore(self.repo)

    async def test_invalid_explicit_product_leaves_campaign_and_queue_unchanged(self):
        for product in ('missing', 'foreign', 'deleted', '', ' initiative ', 3):
            before = deepcopy(self.store.state)
            with self.subTest(product=product), self.assertRaises(WorkflowConflict):
                await self.store.enqueue('org', 'manual', key='request', product_id=product)
            self.assertEqual(self.store.state, before)

    async def test_product_selection_is_part_of_creation_idempotency(self):
        campaign = await self.store.enqueue('org', 'manual', key='same', product_id='initiative')
        for product in ('other', None):
            with self.subTest(product=product), self.assertRaises(WorkflowConflict):
                await self.store.enqueue('org', 'manual', key='same', product_id=product)
        self.assertEqual(await self.store.enqueue('org', 'manual', key='same', product_id='initiative'), campaign)

    async def test_generation_cannot_assign_an_unknown_catalog_product(self):
        await self.store.enqueue('org', 'manual')
        job = (await self.store.claim('generate'))[0]
        before = deepcopy(self.store.state)
        with self.assertRaises(WorkflowConflict):
            await self.store.complete_generation(job, {}, {},
                selected_scope={'topic': 'trust', 'product_id': 'missing'})
        self.assertEqual(self.store.state, before)

    async def test_build_progress_cannot_change_approved_scope(self):
        self.repo.seed_brand_passport('org', {'revision': 1})
        campaign = await self.store.enqueue('org', 'manual', product_id='initiative')
        generation = (await self.store.claim('generate'))[0]
        row = await self.store.complete_generation(generation,
            {'brand_revision': 1, 'proof_references': [], 'video_script': []},
            {'passed': True, 'semantic_checked': True, 'checked_brand_revision': 1})
        await self.store.decide_script('org', campaign['id'], 'approve', row['revision'], 'approve')
        build = (await self.store.claim('build'))[0]
        before = deepcopy(self.store.state)
        with self.assertRaises(WorkflowConflict):
            await self.store.update_build(build, {'product_id': 'other'})
        self.assertEqual(self.store.state, before)

    async def test_qualified_proof_is_not_reduced_to_a_prefix(self):
        from services.milo.evidence import valid_proof_points
        from test_milo_pipeline import fixture
        context = fixture()
        context['sources'][0]['content'] += '\nOnly if the approved materials are used.'
        self.assertEqual(valid_proof_points(context), [])

    async def test_approved_job_and_retry_keep_the_reserved_product(self):
        self.repo.seed_brand_passport('org', {'revision': 1})
        campaign = await self.store.enqueue('org', 'manual', product_id='initiative')
        job = (await self.store.claim('generate'))[0]
        artifact = {'brand_revision': 1, 'proof_references': [], 'video_script': []}
        checks = {'passed': True, 'semantic_checked': True, 'checked_brand_revision': 1}
        current = await self.store.complete_generation(job, artifact, checks,
            selected_scope={'product_id': 'initiative', 'topic': 'trust'})
        await self.store.decide_script('org', campaign['id'], 'approve', current['revision'], 'approve')
        build = (await self.store.claim('build'))[0]
        self.assertEqual(build['payload']['product_id'], 'initiative')
        await self.store.update_build(build, {'submission_state': 'provider_failed'})
        await self.store.fail(build, 'ProviderRenderFailed')
        retried = await self.store.retry('org', build['id'], 'retry')
        self.assertEqual(retried['payload']['product_id'], 'initiative')
        self.assertEqual(retried['id'], build['id'])


if __name__ == '__main__':
    unittest.main()
