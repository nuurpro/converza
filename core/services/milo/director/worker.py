"""Short leased ticks for scene rendering, inspection and master assembly.

Submission intent is committed before contacting Vea. A lost response is looked
up using the persisted idempotency key, never converted into a new attempt.
"""
import asyncio
from contextlib import suppress
import logging

from services.workflow.state import WorkflowConflict
from .store import DirectorStore

logger = logging.getLogger('converza.milo.director')


class DirectorWorker:
    def __init__(self, repo, *, renderer, scene_verifier, master_verifier,
                 lease_seconds=600, timeout_seconds=500):
        self.store=DirectorStore(repo)
        self.renderer=renderer
        self.scene_verifier=scene_verifier
        self.master_verifier=master_verifier
        self.lease_seconds=lease_seconds
        self.timeout_seconds=timeout_seconds

    async def _heartbeat(self, task):
        while True:
            await asyncio.sleep(max(1,self.lease_seconds/3))
            await self.store.renew(task,self.lease_seconds)

    async def process(self, task):
        if task.get('submission_uncertain') and not task.get('receipt'):
            reconcile=getattr(self.renderer,'reconcile',None)
            receipt=await reconcile(task) if reconcile else None
            if receipt and receipt.get('task_id'):
                await self.store.submitted(task,receipt)
                task['receipt']=receipt
                task['submission_uncertain']=False
            elif receipt and receipt.get('not_submitted') is True:
                # Only an authoritative absence permits another HTTP submission,
                # always using the original persisted idempotency key.
                task['submission_uncertain']=False
            else:
                await self.store.defer(task,'Renderer receipt reconciliation required',uncertain=True)
                return
        if not task.get('receipt'):
            await self.store.submission_started(task)
            task['submission_uncertain']=True
            receipt=await self.renderer.submit(task)
            await self.store.submitted(task,receipt)
            task['receipt']=receipt
            task['submission_uncertain']=False
        response=await self.renderer.poll(task)
        if not isinstance(response,dict):
            raise ValueError('Renderer status must be an object')
        status=response.get('status','completed' if response.get('artifact_sha256') else 'running')
        if status in ('failed','cancelled','error'):
            await self.store.fail(task,response.get('error','Renderer failed'),response.get('correction'))
            return
        if status not in ('completed','succeeded','success'):
            await self.store.release(task)
            return
        result=response.get('result') or response.get('artifact') or response
        verifier=self.scene_verifier if task['kind']=='scene' else self.master_verifier
        verification=await verifier(task,result)
        if hasattr(verification,'model_dump'):
            verification=verification.model_dump(mode='json')
        if not isinstance(verification,dict) or type(verification.get('passed')) is not bool:
            raise ValueError('Inspection must return an explicit passed boolean')
        await self.store.complete(task,result,verification)

    async def run_once(self, kind=None):
        tasks=await self.store.claim(kind,limit=1,lease_seconds=self.lease_seconds)
        for task in tasks:
            heartbeat=asyncio.create_task(self._heartbeat(task))
            try:
                await asyncio.wait_for(self.process(task),self.timeout_seconds)
            except WorkflowConflict:
                logger.info('director_stale_result org=%s run=%s task=%s',task['org_id'],task['run_id'],task['id'])
            except Exception as exc:
                # Network, unavailable inspection dependencies and unknown provider
                # outcomes keep the same intent, with a visible recoverable error.
                with suppress(WorkflowConflict):
                    await self.store.defer(task,f'{type(exc).__name__}: {exc}',
                        uncertain=task.get('submission_uncertain',False))
                logger.warning('director_deferred run=%s task=%s error_type=%s',task['run_id'],task['id'],type(exc).__name__)
            finally:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError,WorkflowConflict):
                    await heartbeat
        return len(tasks)

    async def run(self):
        while True:
            if not await self.run_once():
                await asyncio.sleep(2)
