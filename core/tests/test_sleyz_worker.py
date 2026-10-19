import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from lib.repository import InMemoryRepository
from services.sleyz.store import SleyzStore


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo=InMemoryRepository()
        self.store=SleyzStore(self.repo)
        self.envelope={'org_id':'a','platform':'telegram','connection_id':'connection','external_message_id':'m1',
            'customer_id':'buyer','customer_handle':'@buyer','text':'It is too expensive','received_at':datetime.now(timezone.utc).isoformat(),'simulated':False}
        self.accepted=await self.store.accept(self.envelope)

    async def test_worker_persists_objections_and_artifact_before_notification(self):
        from services.sleyz.worker import SleyzWorker
        model=AsyncMock(side_effect=[{'intent_score':.5,'product_query':'course','quantity':1,'language':'en',
            'objections':[{'type':'price','text':'too expensive','span':[6,19]}]},
            {'citations':[],'acknowledgement':'concern','next_step':'needs'}])
        worker=SleyzWorker(self.repo,model=model,context_loader=AsyncMock(return_value={'identity':{},'knowledge':[],'products':[]}))
        self.assertEqual(await worker.run_once(),1)
        draft=await self.repo.get_draft(self.accepted['draft_id'])
        self.assertEqual(draft['status'],'AWAITING_HITL')
        self.assertEqual(draft['sleyz_artifact']['detected_objection'],'too expensive')
        self.assertEqual(len(self.repo._sleyz_state['telemetry']),1)
        self.assertEqual(await worker.run_once(),0)

    async def test_worker_failure_keeps_same_retryable_draft_and_sanitizes_error(self):
        from services.sleyz.worker import SleyzWorker
        worker=SleyzWorker(self.repo,model=AsyncMock(side_effect=RuntimeError('private buyer secret')),
            context_loader=AsyncMock(return_value={}))
        await worker.run_once()
        draft=await self.repo.get_draft(self.accepted['draft_id'])
        self.assertEqual(draft['status'],'PENDING_DRAFT')
        self.assertNotIn('private',str(draft))
        self.assertEqual(len(self.repo.drafts),1)
