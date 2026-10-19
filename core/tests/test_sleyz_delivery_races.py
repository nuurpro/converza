"""Delivery transport claims survive unrelated learning revisions and stay fenced."""
from datetime import datetime, timezone
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from lib.repository import InMemoryRepository
from services.sleyz.store import SleyzStore
from services.workflow.publication import deliver_telegram_draft, publish_telegram
from services.workflow.state import WorkflowConflict


class DeliveryLearningRaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = InMemoryRepository()
        self.store = SleyzStore(self.repo)
        envelope = dict(org_id='org',platform='telegram',connection_id='business',external_message_id='1',
            customer_id='42',customer_handle='buyer',text='Question',received_at=datetime.now(timezone.utc).isoformat(),simulated=False)
        await self.store.accept(envelope)
        job = (await self.store.claim())[0]
        draft = await self.store.ready(job,{'draft_reply':'Original'})
        self.draft = await self.repo.transition_draft('org',draft['id'],'edit',draft['revision'],'edit',edited_content='Human final')

    async def learn_midflight(self):
        job = (await self.store.claim_learning())[0]
        await self.store.complete_learning(job,None)

    async def send(self, handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await publish_telegram(repo=self.repo,org_id='org',draft_id=self.draft['id'],
                expected_revision=self.draft['revision'],idempotency_key='deliver',bot_token='test-token',chat_id=42,client=client)

    async def test_success_receipt_survives_two_learning_revisions_during_send(self):
        async def transport(request):
            await self.learn_midflight()
            return httpx.Response(200,json={'ok':True,'result':{'message_id':77,'chat':{'id':42}}})
        delivered = await self.send(transport)
        self.assertEqual(delivered['status'],'PUBLISHED')
        self.assertEqual(delivered['delivery_receipt']['message_id'],77)
        self.assertEqual(delivered['learning_status'],'skipped')
        self.assertEqual(delivered['final_content'],'Human final')

    async def test_uncertain_transport_stays_ambiguous_after_learning_changes(self):
        async def transport(request):
            await self.learn_midflight()
            raise httpx.ReadTimeout('unconfirmed',request=request)
        ambiguous = await self.send(transport)
        self.assertEqual(ambiguous['delivery_status'],'ambiguous')
        with patch('services.workflow.publication.load_telegram_target',AsyncMock(side_effect=ValueError('bad config'))) as load:
            with self.assertRaises(WorkflowConflict):
                await deliver_telegram_draft(repo=self.repo,org_id='org',draft_id=self.draft['id'],
                    expected_revision=ambiguous['revision'],idempotency_key='retry')
            load.assert_not_awaited()
        self.assertEqual((await self.repo.get_draft(self.draft['id']))['delivery_status'],'ambiguous')

    async def test_sending_claim_cannot_be_reset_by_bad_configuration(self):
        sending = await self.repo.transition_draft('org',self.draft['id'],'begin_delivery',self.draft['revision'],'begin',receipt={'attempt_id':'in-flight'})
        with patch('services.workflow.publication.load_telegram_target',AsyncMock(side_effect=ValueError('bad config'))) as load:
            with self.assertRaises(WorkflowConflict):
                await deliver_telegram_draft(repo=self.repo,org_id='org',draft_id=self.draft['id'],
                    expected_revision=sending['revision'],idempotency_key='retry')
            load.assert_not_awaited()

    async def test_finish_delivery_retries_unrelated_cas_changes_but_fences_other_attempt(self):
        from services.workflow.publication import finish_delivery
        draft = await self.repo.transition_draft('org',self.draft['id'],'begin_delivery',self.draft['revision'],'begin',receipt={'attempt_id':'a'})
        draft = await self.repo.transition_draft('org',draft['id'],'claim_delivery',draft['revision'],'claim',receipt={'attempt_id':'a'})
        original = self.repo.transition_draft
        conflicts = 0
        async def transition(*args,**kwargs):
            nonlocal conflicts
            if args[2]=='publish' and conflicts<2:
                conflicts += 1
                async with self.repo._lock:
                    row = self.repo.drafts[0]
                    row['revision'] += 1
            return await original(*args,**kwargs)
        receipt = dict(channel='telegram',message_id=7,attempt_id='a')
        with patch.object(self.repo,'transition_draft',side_effect=transition):
            result = await finish_delivery(repo=self.repo,org_id='org',draft_id=draft['id'],attempt_id='a',
                action='publish',idempotency_key='receipt',receipt=receipt)
        self.assertEqual(result['status'],'PUBLISHED')
        self.assertEqual(conflicts,2)
        self.assertEqual(await finish_delivery(repo=self.repo,org_id='org',draft_id=draft['id'],attempt_id='a',
            action='publish',idempotency_key='receipt',receipt=receipt),result)
        with self.assertRaises(WorkflowConflict):
            await finish_delivery(repo=self.repo,org_id='org',draft_id=draft['id'],attempt_id='different',
                action='publish',idempotency_key='forged',receipt=receipt)

    async def test_learning_revisions_between_begin_and_claim_do_not_strand_delivery(self):
        original = self.repo.transition_draft
        async def transition(*args,**kwargs):
            result = await original(*args,**kwargs)
            if args[2]=='begin_delivery':
                await self.learn_midflight()
            return result
        async def transport(request):
            return httpx.Response(200,json={'ok':True,'result':{'message_id':78,'chat':{'id':42}}})
        with patch.object(self.repo,'transition_draft',side_effect=transition):
            result = await self.send(transport)
        self.assertEqual(result['status'],'PUBLISHED')
        self.assertEqual(result['learning_status'],'skipped')

    async def test_concurrent_and_repeated_cached_begin_calls_send_once(self):
        sends = 0
        async def transport(request):
            nonlocal sends
            sends += 1
            await asyncio.sleep(.03)
            return httpx.Response(200,json={'ok':True,'result':{'message_id':79,'chat':{'id':42}}})
        results = await asyncio.gather(self.send(transport),self.send(transport),return_exceptions=True)
        self.assertEqual(sends,1)
        self.assertEqual(sum(isinstance(r,WorkflowConflict) for r in results),1)
        self.assertEqual((await self.send(transport))['status'],'PUBLISHED')
        self.assertEqual(sends,1)

    async def test_pretransport_claim_retries_cas_without_reusing_claim_key(self):
        from services.workflow.publication import claim_delivery
        draft = await self.repo.transition_draft('org',self.draft['id'],'begin_delivery',self.draft['revision'],'begin',receipt={'attempt_id':'a'})
        original = self.repo.transition_draft
        changes = 0
        async def transition(*args,**kwargs):
            nonlocal changes
            if args[2]=='claim_delivery' and changes<2:
                changes += 1
                async with self.repo._lock:
                    self.repo.drafts[0]['revision'] += 1
            return await original(*args,**kwargs)
        with patch.object(self.repo,'transition_draft',side_effect=transition):
            result = await claim_delivery(repo=self.repo,org_id='org',draft_id=draft['id'],attempt_id='a')
        self.assertTrue(result['delivery_claimed_at'])
        self.assertEqual(changes,2)
        with self.assertRaises(WorkflowConflict):
            await claim_delivery(repo=self.repo,org_id='org',draft_id=draft['id'],attempt_id='a')
