"""Generation scope is server metadata, never inferred from creative copy."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from lib.repository import InMemoryRepository
from services.milo.store import MiloStore
from services.workflow.state import WorkflowConflict


class GenerationScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_offline_evals_cover_authoritative_scope_in_all_languages(self):
        from services.milo.evals.run import run
        report, code = await run()
        cases = {case['id']: case['passed'] for case in report['safety_cases']}
        self.assertEqual(code, 0)
        for language in ('en', 'ru', 'uz'):
            self.assertTrue(cases.get('selected_scope_' + language, False))

    async def asyncSetUp(self):
        self.store = MiloStore(InMemoryRepository())

    async def leased(self, **scope):
        await self.store.enqueue('org', 'manual', **scope)
        return (await self.store.claim('generate'))[0]

    async def test_selected_scope_roundtrips_even_when_compliance_blocks_copy(self):
        job = await self.leased()
        row = await self.store.complete_generation(job, {'product_id': 'model-guess'}, {'passed': False},
            selected_scope={'product_id': 'selected', 'topic': 'durability'})
        self.assertEqual((row['product_id'], row['topic'], row['status']), ('selected', 'durability', 'blocked'))

    async def test_null_product_is_an_explicit_brandwide_selection(self):
        job = await self.leased()
        row = await self.store.complete_generation(job, {}, {'passed': False},
            selected_scope={'product_id': None, 'topic': 'trust'})
        self.assertEqual((row['product_id'], row['topic']), (None, 'trust'))

    async def test_scope_cannot_override_a_reserved_product_or_topic(self):
        job = await self.leased(product_id='reserved', topic='durability')
        before = deepcopy(self.store.state)
        for scope in ({'product_id': 'other', 'topic': 'durability'}, {'product_id': 'reserved', 'topic': 'price'}):
            with self.subTest(scope=scope), self.assertRaises(WorkflowConflict):
                await self.store.complete_generation(job, {}, {}, selected_scope=scope)
            self.assertEqual(self.store.state, before)

    async def test_missing_evidence_does_not_guess_scope_from_artifact(self):
        job = await self.leased()
        row = await self.store.complete_generation(job, {'product_id': 'model-guess'}, {}, ['Need proof'])
        self.assertEqual((row['product_id'], row['topic']), (None, None))

    async def test_sql_rpc_receives_selected_scope_separately_from_artifact(self):
        store = MiloStore(SimpleNamespace(client=object()))
        store._rpc = AsyncMock(return_value={})
        scope = {'product_id': 'selected', 'topic': 'durability'}
        await store.complete_generation({'id': 'job', 'lease_token': 'token'}, {}, {}, selected_scope=scope)
        self.assertEqual(store._rpc.await_args.kwargs['selected_scope'], scope)
