"""Conversation context contains only prior tenant-scoped inbound and delivered replies."""
import asyncio
import os
import unittest
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from lib.repository import InMemoryRepository
from services.sleyz.store import SleyzStore
from services.sleyz.worker import SleyzWorker


class ConversationHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = InMemoryRepository()
        self.store = SleyzStore(self.repo)
        self.worker = SleyzWorker(self.repo)
        self.base = datetime(2026,10,19,tzinfo=timezone.utc)
        self.counter = 0

    async def inbound(self, text, minute, **changes):
        self.counter += 1
        envelope = dict(org_id='org-a',platform='telegram',connection_id='telegram:org-a',
            external_message_id=str(self.counter),customer_id='buyer',customer_handle='buyer',text=text,
            received_at=(self.base+timedelta(minutes=minute)).isoformat(),simulated=False)
        envelope.update(changes)
        accepted = await self.store.accept(envelope)
        return deepcopy(self.store.state['inbox'][accepted['inbound_id']])

    def delivered(self, job, text, minute, **changes):
        draft = next(d for d in self.repo.drafts if d['id']==job['draft_id'])
        draft.update(status='PUBLISHED',final_content=text,delivery_status='delivered',
            delivered_at=(self.base+timedelta(minutes=minute)).isoformat(),
            delivery_receipt={'channel':'telegram','message_id':'receipt'},**changes)
        return draft

    async def test_history_merges_delivered_final_text_with_prior_inbound(self):
        prior = await self.inbound('Recommend a course',0)
        self.delivered(prior,'I recommend the first or second course.',1)
        current = await self.inbound('The second one please',2)
        self.assertEqual(await self.worker.history(current),[
            {'role':'user','content':'Recommend a course'},
            {'role':'assistant','content':'I recommend the first or second course.'},
        ])

    async def test_future_messages_are_filtered_before_twenty_message_limit(self):
        previous = [await self.inbound(f'previous {n}',n) for n in range(25)]
        current = await self.inbound('current',25)
        for n in range(26,60):
            await self.inbound(f'future {n}',n)
        history = await self.worker.history(current)
        self.assertEqual([row['content'] for row in history],[f'previous {n}' for n in range(5,25)])
        self.assertEqual(len(history),20)

    async def test_unpublished_ambiguous_future_and_other_prospect_replies_are_excluded(self):
        prior = await self.inbound('prior',0)
        self.delivered(prior,'future reply',5)
        unpublished = await self.inbound('still waiting',1)
        row = self.delivered(unpublished,'not delivered',1)
        row.update(status='EDITED',delivery_status='ambiguous')
        stranger = await self.inbound('private buyer',0,customer_id='other')
        self.delivered(stranger,'private reply',1)
        another_org = await self.inbound('private org',0,org_id='org-b')
        self.delivered(another_org,'private org reply',1)
        simulated = await self.inbound('simulated buyer',0,simulated=True,connection_id='simulate:telegram')
        self.delivered(simulated,'simulated reply',1)
        current = await self.inbound('current',2)
        self.assertEqual(await self.worker.history(current),[
            {'role':'user','content':'prior'},{'role':'user','content':'still waiting'}])

    async def test_total_limit_applies_after_merging_assistant_events(self):
        for n in range(15):
            prior = await self.inbound(f'buyer {n}',n*2)
            self.delivered(prior,f'final edited {n}',n*2+1)
        current = await self.inbound('current',31)
        history = await self.worker.history(current)
        self.assertEqual(len(history),20)
        self.assertEqual(history[0],{'role':'user','content':'buyer 5'})
        self.assertEqual(history[-1],{'role':'assistant','content':'final edited 14'})

    async def test_same_event_timestamp_retains_accepted_order_and_excludes_later_acceptance(self):
        await self.inbound('first',0)
        await self.inbound('second',0)
        current = await self.inbound('current',0)
        await self.inbound('later',0)
        self.assertEqual(await self.worker.history(current),[
            {'role':'user','content':'first'},{'role':'user','content':'second'}])

@unittest.skipUnless(os.getenv('CONVERZA_WORKFLOW_TEST_DSN'), 'requires isolated PostgreSQL test database')
class PostgresConversationHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from pg_supabase import PgSupabase
        except ModuleNotFoundError:
            from core.tests.pg_supabase import PgSupabase
        from lib.repository import SupabaseRepository
        cls.client = PgSupabase(os.environ['CONVERZA_WORKFLOW_TEST_DSN'])
        cls.repo = SupabaseRepository(cls.client)
        cls.store = SleyzStore(cls.repo)

    def setUp(self):
        self.org = str(uuid.uuid4())
        self.client.table('orgs').insert({'id':self.org}).execute()
        self.base = datetime(2026,10,19,tzinfo=timezone.utc)
        self.counter = 0

    def tearDown(self):
        for table in ('squad_messages','drafts','prospects'):
            self.client.table(table).delete().eq('org_id',self.org).execute()
        self.client.table('orgs').delete().eq('id',self.org).execute()

    def inbound(self, text, minute, **changes):
        self.counter += 1
        envelope = dict(org_id=self.org,platform='telegram',connection_id='history-test',
            external_message_id=str(self.counter),customer_id='buyer',customer_handle='buyer',text=text,
            received_at=(self.base+timedelta(minutes=minute)).isoformat(),simulated=False)
        envelope.update(changes)
        accepted = asyncio.run(self.store.accept(envelope))
        return self.client.table('sleyz_inbound').select('*').eq('org_id',self.org).eq('id',accepted['inbound_id']).limit(1).execute().data[0]

    def test_real_queries_filter_before_limit_and_merge_authoritative_delivered_final(self):
        for n in range(25):
            prior = self.inbound(f'previous {n}',n*2)
            if n == 24:
                self.client.table('drafts').update({'status':'PUBLISHED','delivery_status':'delivered',
                    'draft_content':'wrong generated original','final_content':'authoritative approved final',
                    'delivered_at':(self.base+timedelta(minutes=49)).isoformat(),
                    'delivery_receipt':{'message_id':'sent','channel':'telegram'}}).eq('org_id',self.org).eq('id',prior['draft_id']).execute()
        current = self.inbound('current',50)
        for n in range(51,76):
            self.inbound(f'future {n}',n)
        other = self.inbound('other buyer private',49,customer_id='other')
        self.client.table('drafts').update({'status':'PUBLISHED','delivery_status':'delivered',
            'final_content':'private assistant','delivered_at':(self.base+timedelta(minutes=49)).isoformat(),
            'delivery_receipt':{'message_id':'private','channel':'telegram'}}).eq('org_id',self.org).eq('id',other['draft_id']).execute()
        history = asyncio.run(SleyzWorker(self.repo).history(current))
        self.assertEqual(history,[*[{'role':'user','content':f'previous {n}'} for n in range(6,25)],
                                 {'role':'assistant','content':'authoritative approved final'}])

    def test_equal_acceptance_timestamp_uses_stable_uuid_tie_break(self):
        jobs = [self.inbound(f'tie {n}',0) for n in range(5)]
        current = max(jobs,key=lambda row:row['id'])
        accepted_at = datetime.now(timezone.utc).isoformat()
        self.client.table('sleyz_inbound').update({'created_at':accepted_at}).eq('org_id',self.org).execute()
        current['created_at'] = accepted_at
        history = asyncio.run(SleyzWorker(self.repo).history(current))
        expected = [row['envelope']['text'] for row in sorted(jobs,key=lambda row:row['id']) if row['id'] < current['id']]
        self.assertEqual([row['content'] for row in history],expected)
