import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from lib.repository import InMemoryRepository
from services.sleyz.store import SleyzStore
from services.workflow.state import WorkflowConflict


class SleyzStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.store = SleyzStore(self.repo)
        self.envelope = dict(org_id='org', platform='telegram', connection_id='business',
            external_message_id='1', customer_id='42', customer_handle='buyer', text='Too expensive',
            received_at=datetime.now(timezone.utc).isoformat(), simulated=False)

    async def generated(self, **changes):
        accepted = await self.store.accept({**self.envelope, **changes})
        job = (await self.store.claim())[0]
        draft = await self.store.ready(job, {'schema_version': 1, 'draft_reply': 'Original reply'})
        return accepted, job, draft

    async def test_accept_is_atomic_deduplicated_and_tenant_scoped(self):
        results = await asyncio.gather(*(self.store.accept(self.envelope) for _ in range(10)))
        self.assertEqual(len({x['draft_id'] for x in results}), 1)
        self.assertEqual(sum(not x['duplicate'] for x in results), 1)
        other = await self.store.accept({**self.envelope, 'org_id': 'other'})
        self.assertNotEqual(other['draft_id'], results[0]['draft_id'])
        self.assertEqual(len(await self.store.claim(limit=10)), 2)
        self.assertEqual(await self.store.claim(), [])

    async def test_expired_lease_reuses_draft_and_fences_old_worker(self):
        accepted = await self.store.accept(self.envelope)
        old = (await self.store.claim())[0]
        self.repo._sleyz_state['inbox'][old['id']]['lease_until'] = 0
        new = (await self.store.claim())[0]
        self.assertEqual(new['draft_id'], accepted['draft_id'])
        self.assertNotEqual(old['lease_token'], new['lease_token'])
        with self.assertRaises(WorkflowConflict):
            await self.store.ready(old, {'draft_reply': 'Stale'})
        draft = await self.store.ready(new, {'draft_reply': 'Fresh'})
        self.assertEqual(draft['draft_content'], 'Fresh')
        event = next(e for e in reversed(self.repo.events) if e['type'] == 'draft_transition')
        self.assertEqual(event['payload']['row']['sleyz_artifact']['draft_reply'], 'Fresh')

    async def test_failure_is_bounded_and_sanitized(self):
        await self.store.accept(self.envelope)
        for _ in range(3):
            job = (await self.store.claim())[0]
            self.assertTrue(await self.store.fail(job, 'secret buyer text token=oops'))
            self.repo._sleyz_state['inbox'][job['id']]['available_at'] = 0
        self.assertEqual(await self.store.claim(), [])
        draft = self.repo.drafts[0]
        self.assertEqual(draft['generation_status'], 'failed')
        self.assertNotIn('secret', draft['generation_error'])

    async def test_edited_approval_enqueues_exact_snapshot_once(self):
        _, _, d = await self.generated()
        d = await self.repo.transition_draft('org', d['id'], 'edit', d['revision'], 'edit', edited_content='Approved reply')
        self.assertEqual(d['learning_status'], 'pending')
        jobs = await self.store.claim_learning()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['original_content'], 'Original reply')
        self.assertEqual(jobs[0]['final_content'], 'Approved reply')
        self.assertGreater((await self.repo.get_draft(d['id']))['revision'], d['revision'])
        self.assertTrue(await self.store.complete_learning(jobs[0], {'content': 'Be concise', 'atoms': [{'rule': 'Be concise'}]}))
        self.assertEqual(self.repo._sleyz_state['corrections'][0]['metadata']['priority'], 2)
        self.assertFalse(await self.store.complete_learning(jobs[0], None))

    async def test_simulation_excluded_from_learning_and_resolution(self):
        _, _, d = await self.generated(simulated=True)
        d = await self.repo.transition_draft('org', d['id'], 'edit', d['revision'], 'edit', edited_content='Edited')
        self.assertEqual(await self.store.claim_learning(), [])
        with self.assertRaises(WorkflowConflict):
            await self.repo.transition_draft('org', d['id'], 'begin_delivery', d['revision'], 'send', receipt={'attempt_id':'a'})

    async def test_telemetry_deduplicates_and_refresh_links_replacement(self):
        accepted, job, d = await self.generated()
        objections = [{'type': 'price', 'text': 'Too expensive', 'span': [0, 13]}]
        await self.store.telemetry(job, objections)
        await self.store.telemetry(job, objections)
        self.assertEqual(len(self.repo._sleyz_state['telemetry']), 1)
        with self.assertRaises(WorkflowConflict):
            await self.store.telemetry(job, [{'type':'price','text':'fabricated','span':[0,10]}])
        replacement = await self.store.refresh('org', d['id'], d['revision'], 'refresh')
        self.assertEqual(await self.store.refresh('org', d['id'], d['revision'], 'refresh'), replacement)
        self.assertNotEqual(accepted['draft_id'], replacement['draft_id'])
        self.assertEqual((await self.repo.get_draft(d['id']))['superseded_by'], replacement['draft_id'])
        with self.assertRaises(WorkflowConflict):
            await self.store.refresh('other', d['id'], d['revision'], 'wrong')

    async def test_learning_failures_can_be_retried_without_blocking_approval(self):
        _, _, d = await self.generated()
        d = await self.repo.transition_draft('org', d['id'], 'edit', d['revision'], 'edit', edited_content='Approved reply')
        for _ in range(3):
            job = (await self.store.claim_learning())[0]
            await self.store.fail_learning(job, 'sensitive')
            self.repo._sleyz_state['learning'][job['id']]['available_at'] = 0
        self.assertEqual(await self.store.claim_learning(), [])
        self.assertEqual((await self.repo.get_draft(d['id']))['status'], 'EDITED')
        await self.store.retry_learning('org', d['id'])
        self.assertEqual(len(await self.store.claim_learning()), 1)

    async def test_generation_retry_resets_same_inbox_and_returns_cas_draft(self):
        accepted = await self.store.accept(self.envelope)
        for _ in range(3):
            job = (await self.store.claim())[0]
            await self.store.fail(job, 'provider')
            self.repo._sleyz_state['inbox'][job['id']]['available_at'] = 0
        d = await self.repo.get_draft(accepted['draft_id'])
        result = await self.store.retry_generation('org',d['id'],d['revision'],'retry')
        self.assertEqual(result['id'], d['id'])
        self.assertEqual(result['generation_status'], 'pending')
        self.assertIsNone(result['generation_error'])
        self.assertEqual(await self.store.retry_generation('org',d['id'],d['revision'],'retry'),result)
        self.assertEqual((await self.store.claim())[0]['attempts'],1)
        with self.assertRaises(WorkflowConflict):
            await self.store.retry_generation('other',d['id'],result['revision'],'wrong')

    async def test_no_rule_learning_skips_without_correction(self):
        _, _, d = await self.generated()
        await self.repo.transition_draft('org',d['id'],'edit',d['revision'],'edit',edited_content='Approved')
        job = (await self.store.claim_learning())[0]
        self.assertTrue(await self.store.complete_learning(job,None))
        self.assertEqual((await self.repo.get_draft(d['id']))['learning_status'],'skipped')
        self.assertEqual(self.store.state['corrections'],[])

    async def test_retry_http_endpoint_keeps_inbound_generation_in_durable_worker(self):
        import httpx
        from fastapi import FastAPI
        from types import SimpleNamespace
        from lib.workflow_routes import create_workflow_router
        accepted = await self.store.accept(self.envelope)
        for _ in range(3):
            job = (await self.store.claim())[0]
            await self.store.fail(job,'provider')
            self.store.state['inbox'][job['id']]['available_at'] = 0
        draft = await self.repo.get_draft(accepted['draft_id'])
        async def auth():
            return SimpleNamespace(user_id='owner')
        app = FastAPI()
        app.include_router(create_workflow_router(lambda:self.repo,auth,lambda user,org:None))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response = await client.post(f"/api/drafts/{draft['id']}/retry-generation",json={'expected_revision':draft['revision']},headers={'Idempotency-Key':'http-retry'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['id'],draft['id'])
        self.assertEqual(len(self.store.state['inbox']),1)
        self.assertEqual((await self.store.claim())[0]['attempts'],1)

    async def test_refresh_shares_workflow_idempotency_namespace(self):
        _, _, draft = await self.generated()
        draft = await self.repo.transition_draft('org',draft['id'],'approve',draft['revision'],'shared-key')
        with self.assertRaises(WorkflowConflict):
            await self.store.refresh('org',draft['id'],draft['revision'],'shared-key')

    async def test_telemetry_invalid_batch_has_no_partial_observations(self):
        _, job, _ = await self.generated()
        with self.assertRaises(WorkflowConflict):
            await self.store.telemetry(job,[{'type':'price','text':'Too expensive','span':[0,13]},
                {'type':'other','text':'wrong','span':[0,5]}])
        self.assertEqual(self.store.state['telemetry'],[])
