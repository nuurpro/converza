import asyncio
import unittest
import httpx
from unittest.mock import AsyncMock, patch

from lib.repository import InMemoryRepository


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_vea_internal_recommendation_does_not_render_or_create_draft(self):
        from lib.switchboard import run_agent
        repo=InMemoryRepository()
        with patch('lib.switchboard.classify_output',AsyncMock(return_value='internal_recommendation')), patch('lib.switchboard.call_engine',AsyncMock(return_value='Use shorter scenes for retention.')), patch('lib.switchboard.call_moneyprinterturbo',AsyncMock(return_value={'video_url':'https://example.invalid/unused.mp4'})) as render:
            result=await run_agent(org_id='a',agent_slug='vea',text='Analyze the scene pacing for the owner. Do not render a video.',triggered_by='owner',repo=repo)
        render.assert_not_awaited()
        self.assertEqual(repo.drafts,[])
        self.assertEqual(result['response'],'Use shorter scenes for retention.')

    async def asyncSetUp(self):
        self.repo = InMemoryRepository()
        self.draft = await self.repo.create_draft('a', 'sleyz', 'Too expensive', '', prospect_id='buyer-1')

    async def action(self, action, revision=None, key=None, **kw):
        return await self.repo.transition_draft('a', self.draft['id'], action,
            revision or self.draft['revision'], key or action, **kw)

    async def ready(self):
        self.draft = await self.action('ready', edited_content='Current answer')

    async def test_creation_precedes_generation_and_failure_is_retryable(self):
        self.assertEqual(self.draft['status'], 'PENDING_DRAFT')
        self.draft = await self.action('generation_failed', error='provider unavailable')
        self.assertEqual(self.draft['status'], 'PENDING_DRAFT')
        self.assertTrue(self.draft['generation_error'])
        self.draft = await self.action('retry_generation')
        self.assertIsNone(self.draft['generation_error'])
        await self.ready()
        self.assertEqual(self.draft['status'], 'AWAITING_HITL')

    async def test_cas_concurrent_decisions_and_idempotency(self):
        await self.ready()
        results = await asyncio.gather(self.action('approve'), self.action('reject'), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, Exception) for r in results), 1)
        approved = await self.action('approve')
        self.assertEqual(approved['status'], 'APPROVED')
        self.assertEqual(approved['revision'], 3)
        with self.assertRaises(ValueError):
            await self.action('edit', key='approve', edited_content='different')

    async def test_rejected_terminal_and_tenant_isolation(self):
        await self.ready()
        self.draft = await self.action('reject')
        with self.assertRaises(ValueError):
            await self.action('approve')
        with self.assertRaises(KeyError):
            await self.repo.transition_draft('other', self.draft['id'], 'approve', 3, 'other')

    async def test_receipt_required_before_publication_and_explicit_resolution(self):
        await self.ready()
        self.draft = await self.action('edit', edited_content='Exact final answer')
        with self.assertRaises(ValueError):
            await self.action('publish')
        with self.assertRaises(ValueError):
            await self.action('resolve')
        self.draft = await self.action('begin_delivery', receipt={'attempt_id':'attempt-1'})
        self.draft = await self.action('delivery_ambiguous', error='timeout')
        with self.assertRaises(ValueError):
            await self.action('begin_delivery')
        self.draft = await self.action('publish', receipt={'channel':'telegram', 'message_id':23, 'attempt_id':'attempt-1'})
        self.assertIsNone(self.draft['resolved_at'])
        self.draft = await self.action('resolve')
        self.assertIsNotNone(self.draft['resolved_at'])

    async def test_snapshot_cursor_replay_is_scoped_monotonic_and_copied(self):
        snapshot = await self.repo.snapshot('a')
        await self.repo.insert_squad_message('other', 'owner', 'private')
        await self.repo.insert_squad_message('a', 'owner', 'hello')
        await self.ready()
        events = await self.repo.read_events('a', snapshot['cursor'])
        self.assertEqual([r['id'] for r in events], [2, 3])
        self.assertEqual([r['type'] for r in events], ['squad_message', 'draft_transition'])
        self.assertEqual(snapshot['drafts'][0]['status'], 'PENDING_DRAFT')

    async def test_dashboard_message_count_is_organization_scoped(self):
        await self.repo.insert_squad_message('other','owner','private')
        rows=await self.repo.get_dashboard_stats('a')
        self.assertEqual(next(r['value'] for r in rows if r['label']=='Squad messages'),'0')

    async def test_telegram_validates_application_receipt_and_never_resends_ambiguous(self):
        from services.workflow.publication import publish_telegram
        await self.ready()
        self.draft = await self.action('approve')
        calls = []
        async def handle(request):
            calls.append(request)
            raise httpx.ReadTimeout('uncertain', request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            args = dict(repo=self.repo, org_id='a', draft_id=self.draft['id'],
                expected_revision=self.draft['revision'], idempotency_key='send',
                bot_token='test', chat_id=42, client=client)
            result = await publish_telegram(**args)
            self.assertEqual(result['status'], 'APPROVED')
            self.assertEqual(result['delivery_status'], 'ambiguous')
            with self.assertRaises(ValueError):
                await publish_telegram(**args)
            self.assertEqual(len(calls), 1)

    async def test_customer_campaign_is_durable_before_model_generation(self):
        from lib.switchboard import run_agent
        with patch('lib.switchboard.classify_output', AsyncMock(return_value='customer_copy')), patch('lib.switchboard.call_engine',AsyncMock()) as generate:
            result=await run_agent(org_id='a', agent_slug='milo', text='Draft hook', triggered_by='owner', repo=self.repo)
        generate.assert_not_awaited()
        from services.milo.store import MiloStore
        row=await MiloStore(self.repo).get_campaign('a',result['campaign_id'])
        self.assertEqual(row['status'],'queued')

    async def test_internal_recommendation_has_no_draft(self):
        from lib.switchboard import run_agent
        with patch('lib.switchboard.classify_output', AsyncMock(return_value='internal_recommendation')), patch('lib.switchboard.call_engine', AsyncMock(return_value='Review lead qualification')):
            await run_agent(org_id='a', agent_slug='sleyz', text='Recommend process improvements', triggered_by='owner', repo=self.repo)
        self.assertEqual(len(self.repo.drafts), 1)

    async def test_telegram_rejection_is_not_publication_and_success_is_idempotent(self):
        from services.workflow.publication import publish_telegram
        await self.ready()
        self.draft = await self.action('approve')
        calls = []
        def reject(request):
            calls.append(request)
            return httpx.Response(200, json={'ok':False,'description':'chat unavailable'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
            row = await publish_telegram(repo=self.repo,org_id='a',draft_id=self.draft['id'],
                expected_revision=self.draft['revision'],idempotency_key='rejectsend',bot_token='test',chat_id=42,client=client)
        self.assertEqual(row['delivery_status'], 'failed')
        self.assertEqual(row['status'], 'APPROVED')
        def accept(request):
            calls.append(request)
            return httpx.Response(200, json={'ok':True,'result':{'message_id':9,'chat':{'id':42}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(accept)) as client:
            args = dict(repo=self.repo,org_id='a',draft_id=row['id'],expected_revision=row['revision'],
                idempotency_key='retrysend',bot_token='test',chat_id=42,client=client)
            delivered = await publish_telegram(**args)
            repeated = await publish_telegram(**args)
        self.assertEqual(delivered, repeated)
        self.assertEqual(delivered['status'],'PUBLISHED')
        self.assertIsNone(delivered['resolved_at'])
        self.assertEqual(len(calls), 2)

    async def test_concurrent_generation_retry_calls_generate_only_once(self):
        from lib.switchboard import retry_generation
        self.draft = await self.action('generation_failed', error='provider failed')
        engine = AsyncMock(return_value='Answer')
        with patch('lib.switchboard.call_engine',engine):
            results = await asyncio.gather(*[retry_generation(org_id='a',draft_id=self.draft['id'],
                expected_revision=self.draft['revision'],idempotency_key='retry',repo=self.repo) for _ in range(2)],return_exceptions=True)
        self.assertEqual(engine.await_count, 1)
        self.assertEqual(sum(isinstance(r, Exception) for r in results),1)

    async def test_receipt_from_another_attempt_cannot_publish(self):
        await self.ready()
        self.draft = await self.action('approve')
        self.draft = await self.action('begin_delivery', receipt={'attempt_id':'actual'})
        with self.assertRaises(ValueError):
            await self.action('publish',receipt={'channel':'telegram','message_id':2,'attempt_id':'different'})


class RepositoryHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_supabase_history_reads_newest_limit_then_restores_chronology(self):
        from types import SimpleNamespace
        from lib.repository import SupabaseRepository
        class Query:
            descending = False
            def table(self, _): return self
            def select(self, _): return self
            def eq(self, *_): return self
            def order(self, column, desc):
                self.descending = desc
                return self
            def limit(self, limit):
                self.bound = limit
                return self
            def execute(self):
                rows = [{'content':i} for i in range(30)]
                rows.sort(key=lambda r:r['content'], reverse=self.descending)
                return SimpleNamespace(data=rows[:self.bound])
        rows = await SupabaseRepository(Query()).get_agent_memory('a','sleyz',20)
        self.assertEqual([r['content'] for r in rows],list(range(10,30)))


class StoredDeliveryTargetTests(unittest.IsolatedAsyncioTestCase):
    def client(self, prospect):
        from types import SimpleNamespace
        class Query:
            def __init__(self, rows): self.rows, self.filters = rows, {}
            def select(self, *_): return self
            def eq(self, key, value): self.filters[key]=value; return self
            def limit(self, *_): return self
            def execute(self):
                return SimpleNamespace(data=[r for r in self.rows if all(r.get(k)==v for k,v in self.filters.items())])
        rows = {'prospects':[prospect], 'tg_connections':[{'org_id':'a','bot_token':'stored-token','business_connection_id':'org-business'}]}
        return SimpleNamespace(table=lambda table:Query(rows[table]))

    async def test_explicit_null_connection_preserves_direct_mode(self):
        from services.workflow.publication import load_telegram_target
        client=self.client({'id':'buyer','org_id':'a','tg_chat_id':42,'business_connection_id':None})
        result=await load_telegram_target(client,'a',{'org_id':'a','prospect_id':'buyer'})
        self.assertEqual(result,{'bot_token':'stored-token','chat_id':42,'business_connection_id':None})

    async def test_target_and_token_are_scoped_to_draft_organization(self):
        from services.workflow.publication import load_telegram_target
        client=self.client({'id':'buyer','org_id':'other','tg_chat_id':42})
        with self.assertRaises(ValueError):
            await load_telegram_target(client,'a',{'org_id':'a','prospect_id':'buyer'})

    async def test_delivery_wrapper_uses_stored_target_and_expected_revision(self):
        from services.workflow.publication import deliver_telegram_draft
        repo=InMemoryRepository()
        d=await repo.create_draft('a','sleyz','Buyer concern','',prospect_id='buyer')
        d=await repo.transition_draft('a',d['id'],'ready',1,'ready',edited_content='Answer')
        d=await repo.transition_draft('a',d['id'],'approve',2,'approve')
        repo.client=self.client({'id':'buyer','org_id':'a','tg_chat_id':42,'business_connection_id':None})
        with patch('services.workflow.publication.publish_telegram',AsyncMock(return_value=d)) as publisher:
            await deliver_telegram_draft(repo=repo,org_id='a',draft_id=d['id'],expected_revision=3,idempotency_key='send')
        self.assertEqual(publisher.call_args.kwargs['chat_id'],42)
        self.assertIsNone(publisher.call_args.kwargs['business_connection_id'])
        self.assertEqual(publisher.call_args.kwargs['expected_revision'],3)


if __name__ == '__main__':
    unittest.main()
