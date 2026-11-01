"""Deterministic pending-feed contract and authorization regressions."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from lib.repository import InMemoryRepository
from services.feed import PendingFeedStore
from services.feed.routes import create_feed_router
from services.milo.store import MiloStore
from services.workflow.state import WorkflowConflict


class PendingFeedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.milo = MiloStore(self.repo)
        self.store = PendingFeedStore(self.repo)
        self.time = '2026-01-01T12:00:00+00:00'

    def draft(self, id, **values):
        row = dict(id=id, org_id='a', agent_slug='sleyz', revision=3,
                   status='AWAITING_HITL', created_at=self.time, draft_content='Verified reply')
        row.update(values)
        self.repo.drafts.append(row)
        return row

    def campaign(self, id, **values):
        row = dict(id=id, org_id='a', revision=4, status='awaiting_review',
                   script_status='pending', artifact={'trigger_reason': 'Buyer objections'},
                   compliance={'passed': True}, missing_evidence=[], build_status=None, created_at=self.time)
        row.update(values)
        self.milo.state['campaigns'][id] = row
        return row

    async def test_mixed_chronology_namespaced_identity_and_cursor_ties(self):
        self.draft('same')
        self.campaign('same')
        self.draft('earlier', created_at='2026-01-01T11:00:00Z')
        first = await self.store.pending('a', limit=2)
        self.assertEqual([r['id'] for r in first['items']], ['workflow:earlier', 'milo:same'])
        second = await self.store.pending('a', limit=2, cursor=first['next_cursor'])
        self.assertEqual([r['id'] for r in second['items']], ['workflow:same'])
        self.assertIsNone(second['next_cursor'])
        row = second['items'][0]
        self.assertEqual((row['kind'], row['source_id'], row['revision']), ('workflow', 'same', 3))
        self.assertEqual(row['payload']['draft']['draft_content'], 'Verified reply')
        with self.assertRaises(ValueError):
            await self.store.pending('b', cursor=first['next_cursor'])

    async def test_exclusions_tenant_isolation_and_blocked_restrictions(self):
        self.draft('foreign', org_id='b')
        self.draft('approved', status='APPROVED')
        self.draft('superseded', superseded_by='new')
        self.draft('old-video', vea_artifact={'superseded': True})
        self.campaign('rejected', script_status='rejected')
        self.campaign('approved-campaign', script_status='approved')
        self.campaign('running', status='generating')
        self.campaign('foreign-campaign', org_id='b')
        self.campaign('blocked', status='blocked', compliance={'passed': False, 'violations': ['Unverified claim']})
        self.campaign('missing', status='needs_evidence', missing_evidence=['Confirm price'])
        result = await self.store.pending('a')
        self.assertEqual([r['source_id'] for r in result['items']], ['blocked', 'missing'])
        self.assertFalse(result['items'][0]['restrictions']['can_approve'])
        self.assertIn('Unverified claim', result['items'][0]['restrictions']['reasons'])
        self.assertIn('Confirm price', result['items'][1]['restrictions']['reasons'])
        self.assertEqual(result['items'][0]['payload']['review_href'], '/agents/milo#campaign-blocked')

    async def test_cursor_boundary_excludes_new_arrivals_and_decisions_refresh(self):
        first_draft = self.draft('a')
        self.draft('b')
        first = await self.store.pending('a', limit=1)
        self.draft('future', created_at='2099-01-01T00:00:00Z')
        first_draft['status'] = 'REJECTED'
        second = await self.store.pending('a', limit=1, cursor=first['next_cursor'])
        self.assertEqual([r['source_id'] for r in second['items']], ['b'])
        self.assertIsNone(second['next_cursor'])
        self.assertEqual([r['source_id'] for r in (await self.store.pending('a'))['items']], ['b'])

    async def test_one_rpc_only_and_no_fallback_when_sql_fails(self):
        rpc = Mock()
        rpc.return_value.execute.return_value.data = dict(items=[], has_more=False, snapshot_at=self.time)
        repo = SimpleNamespace(client=SimpleNamespace(rpc=rpc))
        await PendingFeedStore(repo).pending('a')
        rpc.assert_called_once()
        self.assertEqual(rpc.call_args.args[0], 'pending_approval_feed')
        rpc.return_value.execute.side_effect = RuntimeError('Database unavailable')
        with self.assertRaisesRegex(RuntimeError, 'Database unavailable'):
            await PendingFeedStore(repo).pending('a')

    async def test_feed_keeps_existing_revision_and_duplicate_decision_lifecycles(self):
        self.draft('draft')
        self.campaign('campaign')
        first = await self.store.pending('a')
        self.assertEqual(len(first['items']), 2)
        approved = await self.repo.transition_draft('a','draft','approve',3,'workflow-decision')
        self.assertEqual(await self.repo.transition_draft('a','draft','approve',3,'workflow-decision'),approved)
        with self.assertRaises(WorkflowConflict):
            await self.repo.transition_draft('a','draft','reject',3,'stale-workflow-decision')
        rejected = await self.milo.decide_script('a','campaign','reject',4,'milo-decision')
        self.assertEqual(await self.milo.decide_script('a','campaign','reject',4,'milo-decision'),rejected)
        with self.assertRaises(WorkflowConflict):
            await self.milo.decide_script('a','campaign','reject',4,'stale-milo-decision')
        self.assertEqual((await self.store.pending('a'))['items'], [])

    async def test_invalid_cursor_and_limit_rejected_before_query(self):
        for cursor in ('not-json', 'x' * 2049):
            with self.assertRaises(ValueError):
                await self.store.pending('a', cursor=cursor)
        for limit in (0, 101, True):
            with self.assertRaises(ValueError):
                await self.store.pending('a', limit=limit)


class PendingFeedRouteTests(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.owner = Mock(side_effect=lambda user, org: None if org == 'a' else self.denied())
        async def auth():
            return SimpleNamespace(user_id='owner')
        self.app = FastAPI()
        self.app.include_router(create_feed_router(lambda: self.repo, auth, self.owner))
        self.client = TestClient(self.app)

    @staticmethod
    def denied():
        raise HTTPException(403, 'Wrong organization')

    def test_authenticated_owner_required_and_no_cache(self):
        result = self.client.get('/api/feed/pending?org_id=a')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.owner.assert_called_with('owner', 'a')
        self.assertEqual(self.client.get('/api/feed/pending?org_id=b').status_code, 403)
        self.assertEqual(self.client.get('/api/feed/pending?org_id=a&limit=101').status_code, 422)
        self.assertEqual(self.client.get('/api/feed/pending?org_id=a&cursor=bad').status_code, 422)
        self.assertEqual(self.client.get('/api/feed/pending').status_code, 422)

    def test_authentication_failure_never_reads_feed(self):
        async def auth():
            raise HTTPException(401, 'Sign in required')
        app = FastAPI()
        get_repo = Mock()
        app.include_router(create_feed_router(get_repo, auth, self.owner))
        self.assertEqual(TestClient(app).get('/api/feed/pending?org_id=a').status_code, 401)
        get_repo.assert_not_called()
