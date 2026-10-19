"""Ingress authentication and approved cross-platform transport contracts."""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from lib.repository import InMemoryRepository

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


class ChannelContracts(unittest.TestCase):
    def test_instagram_batch_is_scoped_and_echoes_are_ignored(self):
        from services.sleyz.channels import normalize_instagram
        payload = {'object':'instagram','entry':[{'id':'123','messaging':[
            {'sender':{'id':'buyer'},'recipient':{'id':'123'},'timestamp':1000,'message':{'mid':'m1','text':'price?'}},
            {'sender':{'id':'123'},'message':{'mid':'m2','text':'echo','is_echo':True}},
            {'sender':{'id':'buyer'},'message':{'mid':'m3','attachments':[]}},
        ]}]}
        rows = normalize_instagram(payload, {'123':{'org_id':'org-a','access_token':'secret'}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['org_id'], 'org-a')
        self.assertEqual(rows[0]['customer_handle'], 'buyer')
        self.assertEqual(rows[0]['external_message_id'], 'm1')
        self.assertNotIn('secret', str(rows))
        self.assertEqual(normalize_instagram(payload, {}), [])

    def test_signature_is_raw_body_bound_and_missing_credentials_fail_closed(self):
        from services.sleyz.channels import valid_instagram_signature
        body = b'{"entry":[]}'
        signature = 'sha256=' + hmac.new(b'secret', body, hashlib.sha256).hexdigest()
        self.assertTrue(valid_instagram_signature(body, signature, 'secret'))
        self.assertFalse(valid_instagram_signature(body + b' ', signature, 'secret'))
        self.assertFalse(valid_instagram_signature(body, signature, ''))

    def test_instagram_webhook_waits_for_durable_accept_and_returns_503_on_failure(self):
        from services.sleyz.channels import create_instagram_router
        accept = AsyncMock(return_value={'inbound_id':'i','draft_id':'d','duplicate':False})
        app = FastAPI()
        app.include_router(create_instagram_router(lambda: object(), accept=accept))
        payload = {'object':'instagram','entry':[{'id':'123','messaging':[
            {'sender':{'id':'buyer'},'recipient':{'id':'123'},'timestamp':1000,'message':{'mid':'m1','text':'price?'}}]}]}
        body = json.dumps(payload).encode()
        signature = 'sha256=' + hmac.new(b'secret', body, hashlib.sha256).hexdigest()
        with patch.dict(os.environ, {'INSTAGRAM_APP_SECRET':'secret','INSTAGRAM_VERIFY_TOKEN':'verify','INSTAGRAM_CONNECTIONS':json.dumps({'123':{'org_id':'org-a','access_token':'private'}})}), TestClient(app) as client:
            self.assertEqual(client.get('/webhooks/instagram', params={'hub.mode':'subscribe','hub.verify_token':'verify','hub.challenge':'123'}).text, '123')
            self.assertEqual(client.post('/webhooks/instagram', content=body).status_code, 403)
            self.assertEqual(client.post('/webhooks/instagram', content=body, headers={'X-Hub-Signature-256':signature}).status_code, 200)
            accept.assert_awaited_once()
            accept.side_effect = RuntimeError('database unavailable')
            self.assertEqual(client.post('/webhooks/instagram', content=body, headers={'X-Hub-Signature-256':signature}).status_code, 503)


class DeliveryContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = InMemoryRepository()
        row = await self.repo.create_draft('org-a','sleyz','buy','',prospect_id='buyer')
        row = await self.repo.transition_draft('org-a',row['id'],'ready',1,'ready',edited_content='original')
        self.draft = await self.repo.transition_draft('org-a',row['id'],'edit',row['revision'],'edit',edited_content='approved final')

    async def test_instagram_sends_authoritative_copy_and_receipt_once(self):
        from services.sleyz.publication import publish_instagram
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'recipient_id':'buyer','message_id':'sent-1'}
        client = SimpleNamespace(post=AsyncMock(return_value=response))
        sent = await publish_instagram(repo=self.repo, org_id='org-a',draft_id=self.draft['id'],expected_revision=self.draft['revision'],idempotency_key='send',account_id='123',customer_id='buyer',access_token='secret',client=client)
        self.assertEqual(sent['status'], 'PUBLISHED')
        self.assertEqual(client.post.await_args.kwargs['json']['message']['text'], 'approved final')
        again = await publish_instagram(repo=self.repo, org_id='org-a',draft_id=self.draft['id'],expected_revision=self.draft['revision'],idempotency_key='send',account_id='123',customer_id='buyer',access_token='secret',client=client)
        self.assertEqual(again['status'], 'PUBLISHED')
        self.assertEqual(client.post.await_count, 1)

    async def test_mismatched_receipt_is_ambiguous_and_cannot_resend(self):
        from services.sleyz.publication import publish_instagram
        from services.workflow import WorkflowConflict
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'recipient_id':'other','message_id':'sent-1'}
        client = SimpleNamespace(post=AsyncMock(return_value=response))
        args = dict(repo=self.repo,org_id='org-a',draft_id=self.draft['id'],expected_revision=self.draft['revision'],idempotency_key='send',account_id='123',customer_id='buyer',access_token='secret',client=client)
        sent = await publish_instagram(**args)
        self.assertEqual(sent['delivery_status'], 'ambiguous')
        with self.assertRaises(WorkflowConflict):
            await publish_instagram(**{**args,'expected_revision':sent['revision'],'idempotency_key':'again'})
        self.assertEqual(client.post.await_count, 1)

    async def test_simulated_draft_is_never_published(self):
        from services.sleyz.publication import deliver_sleyz_draft
        self.repo.drafts[0]['simulated'] = True
        with self.assertRaisesRegex(ValueError,'Simulated'):
            await deliver_sleyz_draft(repo=self.repo,org_id='org-a',draft_id=self.draft['id'],expected_revision=self.draft['revision'],idempotency_key='send')

    def test_instagram_window_uses_last_inbound_and_rejects_old_or_future(self):
        from services.sleyz.publication import assert_instagram_window
        now = datetime.now(timezone.utc)
        assert_instagram_window((now-timedelta(hours=23)).isoformat(), now=now)
        for value in ((now-timedelta(hours=25)).isoformat(), (now+timedelta(hours=1)).isoformat(), None):
            with self.assertRaises(ValueError):
                assert_instagram_window(value, now=now)


    async def test_instagram_timeout_is_ambiguous(self):
        import httpx
        from services.sleyz.publication import publish_instagram
        client = SimpleNamespace(post=AsyncMock(side_effect=httpx.ReadTimeout('private transport details')))
        sent = await publish_instagram(repo=self.repo,org_id='org-a',draft_id=self.draft['id'],expected_revision=self.draft['revision'],idempotency_key='timeout',account_id='123',customer_id='buyer',access_token='secret',client=client)
        self.assertEqual(sent['delivery_status'],'ambiguous')
        self.assertEqual(sent['delivery_error'],'ReadTimeout')

    async def test_instagram_definitive_rejection_is_retryable_failure(self):
        import httpx
        from services.sleyz.publication import publish_instagram
        request = httpx.Request('POST','https://graph.instagram.com')
        response = httpx.Response(403,request=request,json={'error':{'message':'permission revoked'}})
        client = SimpleNamespace(post=AsyncMock(return_value=response))
        sent = await publish_instagram(repo=self.repo,org_id='org-a',draft_id=self.draft['id'],expected_revision=self.draft['revision'],idempotency_key='rejected',account_id='123',customer_id='buyer',access_token='secret',client=client)
        self.assertEqual(sent['delivery_status'],'failed')
        self.assertEqual(sent['delivery_error'],'HTTPStatusError')


class SleyzApiContracts(unittest.TestCase):
    def setUp(self):
        from services.sleyz.routes import create_sleyz_router
        self.repo = InMemoryRepository()
        async def auth(authorization: str | None = Header(None)):
            if authorization != 'Bearer owner':
                raise HTTPException(401, 'Authentication required')
            return SimpleNamespace(user_id='owner')
        def owner(user_id, org_id):
            if org_id != 'org-a':
                raise HTTPException(403, 'Organization access denied')
        app = FastAPI()
        app.include_router(create_sleyz_router(lambda: self.repo,auth,owner))
        self.client = TestClient(app)
        self.headers = {'authorization':'Bearer owner','Idempotency-Key':'sim-1'}

    def tearDown(self):
        self.client.close()

    def test_simulation_requires_auth_owner_and_key_then_forces_isolation(self):
        body = {'org_id':'org-a','platform':'instagram','customer_id':'buyer','text':'buy','simulated':False}
        self.assertEqual(self.client.post('/api/simulate/inbound-dm', json=body).status_code,401)
        self.assertEqual(self.client.post('/api/simulate/inbound-dm', json=body,headers={'authorization':'Bearer owner'}).status_code,422)
        self.assertEqual(self.client.post('/api/simulate/inbound-dm', json={**body,'org_id':'org-b'},headers=self.headers).status_code,403)
        with patch('services.sleyz.routes.SleyzStore') as store:
            store.return_value.accept = AsyncMock(return_value={'inbound_id':'inbound','draft_id':'draft','duplicate':False})
            response = self.client.post('/api/simulate/inbound-dm',json=body,headers=self.headers)
        self.assertEqual(response.status_code,202)
        envelope = store.return_value.accept.await_args.args[0]
        self.assertTrue(envelope['simulated'])
        self.assertEqual(envelope['connection_id'],'simulate:instagram')
        self.assertEqual(envelope['external_message_id'],'sim-1')

    def test_connection_status_is_tenant_scoped_and_never_exposes_tokens(self):
        with patch.dict(os.environ, {'INSTAGRAM_CONNECTIONS':json.dumps({'123':{'org_id':'org-a','access_token':'private'},'456':{'org_id':'org-b','access_token':'other'}})}):
            response = self.client.get('/api/sleyz/connections?org_id=org-a',headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertNotIn('private', response.text)
        self.assertNotIn('other', response.text)
        self.assertNotIn('456', response.text)
        self.assertIn('123', response.text)

    def test_simulation_dedup_and_refresh_create_one_replacement_with_fresh_review(self):
        body = {'org_id':'org-a','platform':'telegram','customer_id':'buyer','text':'buy'}
        first = self.client.post('/api/simulate/inbound-dm',json=body,headers=self.headers)
        duplicate = self.client.post('/api/simulate/inbound-dm',json=body,headers=self.headers)
        self.assertEqual(first.status_code,202)
        self.assertEqual(first.json()['draft_id'],duplicate.json()['draft_id'])
        self.assertTrue(duplicate.json()['duplicate'])
        self.assertEqual(len(self.repo.drafts),1)
        draft_id = first.json()['draft_id']
        asyncio.run(self.repo.transition_draft('org-a',draft_id,'ready',1,'ready',edited_content='answer'))
        refresh = self.client.post(f'/api/drafts/{draft_id}/refresh',json={'expected_revision':2},headers={**self.headers,'Idempotency-Key':'refresh'})
        self.assertEqual(refresh.status_code,202)
        again = self.client.post(f'/api/drafts/{draft_id}/refresh',json={'expected_revision':2},headers={**self.headers,'Idempotency-Key':'refresh'})
        self.assertEqual(again.json(),refresh.json())
        replacement = asyncio.run(self.repo.get_draft(refresh.json()['draft_id']))
        self.assertEqual(replacement['status'],'PENDING_DRAFT')
        self.assertTrue(replacement['simulated'])
        self.assertEqual(len(self.repo.drafts),2)
        conflict = self.client.post(f'/api/drafts/{draft_id}/refresh',json={'expected_revision':2},headers={**self.headers,'Idempotency-Key':'another'})
        self.assertEqual(conflict.status_code,409)


class TelegramInboxContracts(unittest.TestCase):
    def test_telegram_persists_authenticated_configured_envelope_before_ack(self):
        from Sleyz.sales_main import app
        from Sleyz.routers import webhook
        body = {'message':{'message_id':7,'date':1000,'text':'buy','from':{'id':11},'chat':{'id':42,'type':'private'}}}
        accept = AsyncMock(return_value={'inbound_id':'i','draft_id':'d','duplicate':False})
        with patch.dict(os.environ,{'SALES_WEBHOOK_SECRET':'secret'}), patch.object(webhook.db,'get_org_by_sales_token',return_value={'org_id':'org-a'}),patch.object(webhook,'accept_inbound',accept,create=True),TestClient(app) as client:
            response = client.post('/webhook',json=body,headers={'X-Telegram-Bot-Api-Secret-Token':'secret'})
            self.assertEqual(response.status_code,200)
            accept.assert_awaited_once()
            envelope = accept.await_args.args[0]
            self.assertEqual(envelope['org_id'],'org-a')
            self.assertEqual(envelope['tg_chat_id'],42)
            self.assertEqual(envelope['external_message_id'],'42:7')
            accept.side_effect = RuntimeError('private database error')
            self.assertEqual(client.post('/webhook',json=body,headers={'X-Telegram-Bot-Api-Secret-Token':'secret'}).status_code,503)

class RealInboxDeliveryContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from services.sleyz.store import SleyzStore
        self.repo = InMemoryRepository()
        self.store = SleyzStore(self.repo)
        self.base = dict(org_id='org-a',platform='instagram',connection_id='123',external_message_id='first',customer_id='buyer',customer_handle='buyer',text='buy',received_at=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat(),simulated=False)
        result = await self.store.accept(self.base)
        self.draft = await self.repo.transition_draft('org-a',result['draft_id'],'ready',1,'ready',edited_content='original')
        self.draft = await self.repo.transition_draft('org-a',result['draft_id'],'approve',self.draft['revision'],'approve')

    async def test_expired_window_stays_failed_until_new_inbound_from_same_connected_buyer(self):
        from services.sleyz.publication import deliver_sleyz_draft
        config = {'123':{'org_id':'org-a','access_token':'private'},'456':{'org_id':'org-a','access_token':'other'}}
        arguments = dict(repo=self.repo,org_id='org-a',draft_id=self.draft['id'],expected_revision=self.draft['revision'],idempotency_key='old')
        with patch.dict(os.environ,{'INSTAGRAM_CONNECTIONS':json.dumps(config)}),patch('services.sleyz.publication.publish_instagram',AsyncMock(return_value={'status':'PUBLISHED'})) as send:
            failed = await deliver_sleyz_draft(**arguments)
            self.assertEqual(failed['delivery_status'],'failed')
            send.assert_not_awaited()
            recent = {**self.base,'external_message_id':'other-account','connection_id':'456','received_at':datetime.now(timezone.utc).isoformat()}
            await self.store.accept(recent)
            failed = await deliver_sleyz_draft(**{**arguments,'expected_revision':failed['revision'],'idempotency_key':'wrong-account'})
            send.assert_not_awaited()
            await self.store.accept({**recent,'external_message_id':'latest','connection_id':'123'})
            result = await deliver_sleyz_draft(**{**arguments,'expected_revision':failed['revision'],'idempotency_key':'current'})
            self.assertEqual(result['status'],'PUBLISHED')
            self.assertEqual(send.await_args.kwargs['customer_id'],'buyer')
            self.assertEqual(send.await_args.kwargs['account_id'],'123')

    async def test_superseded_and_simulated_drafts_are_blocked_before_transport(self):
        from services.sleyz.publication import deliver_sleyz_draft
        replacement = await self.store.refresh('org-a',self.draft['id'],self.draft['revision'],'refresh')
        with self.assertRaisesRegex(ValueError,'Superseded'):
            await deliver_sleyz_draft(repo=self.repo,org_id='org-a',draft_id=self.draft['id'],expected_revision=self.draft['revision']+1,idempotency_key='send')
        simulated = await self.store.accept({**self.base,'connection_id':'simulate:instagram','simulated':True})
        with self.assertRaisesRegex(ValueError,'Simulated'):
            await deliver_sleyz_draft(repo=self.repo,org_id='org-a',draft_id=simulated['draft_id'],expected_revision=1,idempotency_key='send-sim')

    async def test_reporter_routes_simulated_drafts_through_dispatcher(self):
        from Sleyz.agents import reporter
        simulated = await self.store.accept({**self.base,'connection_id':'simulate:telegram','platform':'telegram','simulated':True})
        draft = await self.repo.get_draft(simulated['draft_id'])
        with patch.object(reporter.db,'get_repository',return_value=self.repo):
            with self.assertRaisesRegex(ValueError,'Simulated'):
                await reporter.send_approved_reply(draft['id'],'untrusted',9,None,'org-a',draft['prospect_id'])
class CommerceDeliveryContracts(unittest.IsolatedAsyncioTestCase):
    async def test_changed_catalog_blocks_and_published_retry_returns_same_receipt(self):
        from services.sleyz.publication import deliver_sleyz_draft
        repo = InMemoryRepository()
        draft = await repo.create_draft('org-a','sleyz','buy','',prospect_id='buyer')
        draft = await repo.transition_draft('org-a',draft['id'],'ready',1,'ready',edited_content='answer')
        draft = await repo.transition_draft('org-a',draft['id'],'approve',draft['revision'],'approve')
        repo.drafts[0]['sleyz_artifact'] = {'product_snapshot':[{'id':'gone'}],'checkout_link':None}
        result = await deliver_sleyz_draft(repo=repo,org_id='org-a',draft_id=draft['id'],expected_revision=draft['revision'],idempotency_key='stale')
        self.assertEqual(result['delivery_status'],'failed')
        self.assertIn('Regenerate',result['delivery_error'])
        repo.drafts[0].update(status='PUBLISHED',delivery_status='delivered',delivery_receipt={'message_id':'already'})
        result = await deliver_sleyz_draft(repo=repo,org_id='org-a',draft_id=draft['id'],expected_revision=draft['revision'],idempotency_key='stale')
        self.assertEqual(result['delivery_receipt']['message_id'],'already')

class TelegramImmutableRouteContracts(unittest.IsolatedAsyncioTestCase):
    async def test_later_direct_message_cannot_reroute_previously_approved_business_draft(self):
        from services.sleyz.store import SleyzStore
        from services.sleyz.publication import deliver_sleyz_draft
        repo = InMemoryRepository()
        store = SleyzStore(repo)
        envelope = dict(org_id='org-a',platform='telegram',connection_id='business-original',
            external_message_id='first',customer_id='buyer',customer_handle='buyer',text='buy',
            received_at=datetime.now(timezone.utc).isoformat(),simulated=False,tg_chat_id=42,
            business_connection_id='business-original')
        accepted = await store.accept(envelope)
        draft = await repo.transition_draft('org-a',accepted['draft_id'],'ready',1,'ready',edited_content='answer')
        draft = await repo.transition_draft('org-a',draft['id'],'approve',draft['revision'],'approve')
        await store.accept({**envelope,'external_message_id':'later','connection_id':'telegram:direct:org-a',
                            'tg_chat_id':999,'business_connection_id':None})
        prospect = next(iter(store.state['prospects'].values()))
        self.assertIsNone(prospect['business_connection_id'])
        query = Mock()
        for method in ('select','eq','limit'):
            getattr(query,method).return_value = query
        query.execute.return_value = SimpleNamespace(data=[{'bot_token':'server-secret','business_connection_id':'business-original'}])
        repo.client = Mock()
        repo.client.table.return_value = query
        with patch('services.workflow.publication.publish_telegram',AsyncMock(return_value={'status':'PUBLISHED'})) as publish:
            result = await deliver_sleyz_draft(repo=repo,org_id='org-a',draft_id=draft['id'],expected_revision=draft['revision'],idempotency_key='send')
        self.assertEqual(result['status'],'PUBLISHED')
        self.assertEqual(publish.await_args.kwargs['chat_id'],42)
        self.assertEqual(publish.await_args.kwargs['business_connection_id'],'business-original')
        self.assertEqual(publish.await_args.kwargs['bot_token'],'server-secret')
        repo.client.table.assert_called_once_with('tg_connections')

class DeliveryRaceContracts(unittest.IsolatedAsyncioTestCase):
    async def test_ambiguous_attempt_is_never_reset_by_stale_catalog_validation(self):
        from services.sleyz.publication import deliver_sleyz_draft
        from services.workflow import WorkflowConflict
        repo = InMemoryRepository()
        draft = await repo.create_draft('org-a','sleyz','buy','',prospect_id='buyer')
        draft = await repo.transition_draft('org-a',draft['id'],'ready',1,'ready',edited_content='answer')
        draft = await repo.transition_draft('org-a',draft['id'],'approve',draft['revision'],'approve')
        repo.drafts[0].update(delivery_status='ambiguous',sleyz_artifact={'product_snapshot':[{'id':'gone'}]})
        with self.assertRaises(WorkflowConflict):
            await deliver_sleyz_draft(repo=repo,org_id='org-a',draft_id=draft['id'],expected_revision=draft['revision'],idempotency_key='again')
        self.assertEqual(repo.drafts[0]['delivery_status'],'ambiguous')

    async def test_learning_completion_during_instagram_request_does_not_lose_receipt(self):
        from services.sleyz.store import SleyzStore
        from services.sleyz.publication import publish_instagram
        repo = InMemoryRepository()
        store = SleyzStore(repo)
        accepted = await store.accept(dict(org_id='org-a',platform='instagram',connection_id='123',external_message_id='1',
            customer_id='buyer',customer_handle='buyer',text='buy',received_at=datetime.now(timezone.utc).isoformat(),simulated=False))
        job = (await store.claim())[0]
        draft = await store.ready(job,{'schema_version':1,'draft_reply':'original'})
        draft = await repo.transition_draft('org-a',draft['id'],'edit',draft['revision'],'edit',edited_content='approved final')
        learning = (await store.claim_learning())[0]
        draft = await repo.get_draft(draft['id'])
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'recipient_id':'buyer','message_id':'sent-1'}
        async def transport(*args,**kwargs):
            await store.complete_learning(learning,None)
            return response
        client = SimpleNamespace(post=transport)
        result = await publish_instagram(repo=repo,org_id='org-a',draft_id=draft['id'],expected_revision=draft['revision'],
            idempotency_key='send',account_id='123',customer_id='buyer',access_token='secret',client=client)
        self.assertEqual(result['status'],'PUBLISHED')
        self.assertEqual(result['learning_status'],'skipped')
        self.assertEqual(result['delivery_receipt']['message_id'],'sent-1')


class DeliveryPreclaimRaceContracts(unittest.IsolatedAsyncioTestCase):
    async def test_learning_completion_between_begin_and_claim_does_not_strand_unsent_attempt(self):
        from services.sleyz.store import SleyzStore
        from services.sleyz.publication import publish_instagram
        repo = InMemoryRepository()
        store = SleyzStore(repo)
        await store.accept(dict(org_id='org-a',platform='instagram',connection_id='123',external_message_id='1',
            customer_id='buyer',customer_handle='buyer',text='buy',received_at=datetime.now(timezone.utc).isoformat(),simulated=False))
        job = (await store.claim())[0]
        draft = await store.ready(job,{'schema_version':1,'draft_reply':'original'})
        draft = await repo.transition_draft('org-a',draft['id'],'edit',draft['revision'],'edit',edited_content='approved final')
        learning = (await store.claim_learning())[0]
        draft = await repo.get_draft(draft['id'])
        transition = repo.transition_draft
        async def with_learning(org_id,draft_id,action,*args,**kwargs):
            result = await transition(org_id,draft_id,action,*args,**kwargs)
            if action == 'begin_delivery':
                await store.complete_learning(learning,None)
            return result
        repo.transition_draft = with_learning
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'recipient_id':'buyer','message_id':'sent-1'}
        client = SimpleNamespace(post=AsyncMock(return_value=response))
        result = await publish_instagram(repo=repo,org_id='org-a',draft_id=draft['id'],expected_revision=draft['revision'],
            idempotency_key='send',account_id='123',customer_id='buyer',access_token='secret',client=client)
        self.assertEqual(result['status'],'PUBLISHED')
        self.assertEqual(result['learning_status'],'skipped')
        self.assertEqual(client.post.await_count,1)
