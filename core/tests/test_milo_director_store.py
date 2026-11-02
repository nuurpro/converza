import asyncio
import unittest
from lib.repository import InMemoryRepository
from services.milo.director.store import DirectorStore
from services.milo.director.worker import DirectorWorker
from services.milo.director.documents import DirectorDocuments
from services.milo.director.contracts import Storyboard
from services.workflow.state import WorkflowConflict


class DirectorStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = InMemoryRepository()
        self.store = DirectorStore(self.repo)
        self.scenes = [{'scene_index': i, 'narration': str(i), 'target_duration_seconds': 2} for i in range(1, 3)]

    async def start(self, **kw):
        kw.setdefault('reuse_context',{'brand_revision':1,'assets':'fixture-v1','renderer':'fixture-v1'})
        return await self.store.create_run('org', 'campaign', 1, self.scenes, key='build', **kw)

    async def pass_task(self, task):
        await self.store.submitted(task, {'task_id': task['id']})
        return await self.store.complete(task, {'artifact_sha256': 'a' * 64, 'video_url': 'https://example.test/a.mp4'}, {'passed': True})

    async def test_sequence_and_atomic_final_promotion(self):
        await self.start()
        first = (await self.store.claim())[0]
        self.assertEqual(first['scene_index'], 1)
        self.assertEqual(await self.store.claim(), [])
        await self.pass_task(first)
        second = (await self.store.claim())[0]
        self.assertEqual(second['scene_index'], 2)
        await self.pass_task(second)
        master = (await self.store.claim())[0]
        self.assertEqual(master['kind'], 'master')
        final = await self.pass_task(master)
        self.assertEqual(final['state'], 'AWAITING_HITL')
        self.assertEqual(len(self.repo.drafts), 1)
        await self.store.complete(master, {}, {'passed': True})
        self.assertEqual(len(self.repo.drafts), 1)
        events = await self.repo.read_events('org', 0)
        self.assertTrue(any('SCENE_VERIFIED' in str(e) for e in events))

    async def test_retry_dag_and_exhaustion_blocks_successors(self):
        run = await self.start()
        prior = None
        for attempt in range(1, 4):
            task = (await self.store.claim())[0]
            self.assertEqual(task['attempt'], attempt)
            self.assertEqual(task['parent_attempt_id'], prior)
            prior = task['id']
            await self.store.fail(task, 'caption missing', correction={'violations': ['caption missing']})
        self.assertEqual((await self.store.get('org', run['id']))['state'], 'BLOCKED')
        self.assertEqual(await self.store.claim(), [])

    async def test_claim_fencing_tenant_and_expired_submission_reconciliation(self):
        run = await self.start()
        claims = await asyncio.gather(*[self.store.claim() for _ in range(5)])
        self.assertEqual(sum(len(c) for c in claims), 1)
        task = next(c[0] for c in claims if c)
        await self.store.submission_started(task)
        await self.store.release(task)
        reclaimed = (await self.store.claim())[0]
        self.assertTrue(reclaimed['submission_uncertain'])
        self.assertNotEqual(reclaimed['lease_token'], task['lease_token'])
        with self.assertRaises(WorkflowConflict):
            await self.store.submitted(task, {'task_id': 'stale'})
        with self.assertRaises(WorkflowConflict):
            await self.store.get('other', run['id'])

    async def test_idempotency_supersession_and_cached_traversal(self):
        old = await self.start()
        self.assertEqual((await self.start())['id'], old['id'])
        await self.pass_task((await self.store.claim())[0])
        second = (await self.store.claim())[0]
        new = await self.store.create_run('org', 'campaign', 1, self.scenes, key='edit', parent_run_id=old['id'],
            reuse_context={'brand_revision':1,'assets':'fixture-v1','renderer':'fixture-v1'})
        self.assertEqual(new['scenes'][0]['state'], 'SCENE_VERIFIED')
        with self.assertRaises(WorkflowConflict):
            await self.pass_task(second)
        next_task = (await self.store.claim())[0]
        self.assertEqual(next_task['run_id'], new['id'])
        self.assertEqual(next_task['scene_index'], 2)
        with self.assertRaises(WorkflowConflict):
            await self.store.create_run('org', 'campaign', 2, self.scenes, key='edit')

    async def test_unsigned_run_cannot_dispatch(self):
        run = await self.start(script_approved=False)
        self.assertEqual(run['state'], 'AWAITING_SCRIPT_APPROVAL')
        self.assertEqual(await self.store.claim(), [])

    async def test_master_retry_uses_verified_scenes_and_promotes_once(self):
        run=await self.start()
        await self.pass_task((await self.store.claim())[0])
        await self.pass_task((await self.store.claim())[0])
        master=(await self.store.claim())[0]
        manifest=master['specification']
        await self.store.submitted(master,{'task_id':master['id']})
        await self.store.complete(master,{'artifact_sha256':'a'*64},{'passed':False,'violations':['ducking']})
        retry=(await self.store.claim())[0]
        self.assertEqual(retry['attempt'],2)
        self.assertEqual(retry['specification'],manifest)
        await self.pass_task(retry)
        row=await self.store.get('org',run['id'])
        self.assertEqual(len([t for t in row['tasks'] if t['kind']=='scene']),2)
        self.assertEqual(len(self.repo.drafts),1)

    async def test_uncertain_submit_reconciles_without_duplicate_render(self):
        run=await self.start()
        class Renderer:
            submissions=0
            recovered=False
            async def submit(self,task):
                self.submissions+=1
                raise TimeoutError('lost response')
            async def reconcile(self,task):
                self.recovered=True
                return {'task_id':'known-remote-task'}
            async def poll(self,task):
                return {'status':'completed','result':{'artifact_sha256':'a'*64,'video_url':'https://example.test/a.mp4'}}
        async def verify(task,result): return {'passed':True}
        renderer=Renderer()
        worker=DirectorWorker(self.repo,renderer=renderer,scene_verifier=verify,master_verifier=verify)
        await worker.run_once()
        self.assertEqual(await self.store.claim(),[])
        await self.store.recover('org',run['id'])
        await worker.run_once()
        self.assertTrue(renderer.recovered)
        self.assertEqual(renderer.submissions,1)
        next_task=(await self.store.claim())[0]
        self.assertEqual(next_task['scene_index'],2)

    async def test_poll_running_preserves_receipt_and_attempt(self):
        await self.start()
        class Renderer:
            submissions=0
            async def submit(self,task):
                self.submissions+=1
                return {'task_id':'remote'}
            async def poll(self,task): return {'status':'running'}
        async def verify(task,result): raise AssertionError('not ready')
        renderer=Renderer()
        worker=DirectorWorker(self.repo,renderer=renderer,scene_verifier=verify,master_verifier=verify)
        await worker.run_once()
        await worker.run_once()
        self.assertEqual(renderer.submissions,1)
        task=(await self.store.claim())[0]
        self.assertEqual(task['attempt'],1)
        self.assertEqual(task['receipt']['task_id'],'remote')

    async def test_document_edit_fences_old_attempt_before_successor_creation(self):
        docs=DirectorDocuments(self.repo)
        self.scenes=Storyboard.model_validate(dict(revision=1,scenes=[dict(scene_index=1,total_scenes=1,
            target_duration_sec=2,narration_chunk='Exact words',
            visual_directive=dict(prompt='Product',subject_action='Still',camera_movement='Static',lighting_style='Soft'),
            asset_constraints={},overlay_text=dict(text='Caption',end_sec=2))])).model_dump(mode='json')['scenes']
        await docs.command('org','campaign','initialize',board=dict(revision=1,scenes=self.scenes,narration_approved=True),
                           campaign_revision=1,key='init')
        run=await self.start()
        task=(await self.store.claim())[0]
        changed=[{**self.scenes[0],'narration_chunk':'Different words'}]
        preview=await docs.preview('org','campaign',1,dict(base_revision=1,narration_changed=True,
            unresolved_instructions=[],scenes=changed))
        await docs.command('org','campaign','apply',expected_revision=1,preview_id=preview['preview_id'],key='edit')
        self.assertTrue((await self.store.get('org',run['id']))['document_fenced'])
        with self.assertRaises(WorkflowConflict): await self.pass_task(task)
        self.assertEqual(await self.store.claim(),[])

    async def test_missing_or_changed_reuse_context_rebuilds_verified_scenes(self):
        old=await self.start()
        await self.pass_task((await self.store.claim())[0])
        changed=await self.store.create_run('org','campaign',1,self.scenes,'changed-assets',parent_run_id=old['id'],
            reuse_context={'brand_revision':1,'assets':'fixture-v2','renderer':'fixture-v1'})
        self.assertIsNone(changed['scenes'][0]['verified'])
        self.assertEqual((await self.store.claim())[0]['scene_index'],1)
        absent=await self.store.create_run('org','campaign',1,self.scenes,'unknown-assets',parent_run_id=changed['id'])
        self.assertIsNone(absent['scenes'][0]['verified'])

    async def test_recovery_key_replay_and_cross_run_conflict(self):
        run=await self.start()
        task=(await self.store.claim())[0]
        await self.store.defer(task,'Dependency unavailable')
        recovered=await self.store.recover('org',run['id'],key='recover',expected_revision=1)
        replay=await self.store.recover('org',run['id'],key='recover',expected_revision=1)
        self.assertEqual(recovered,replay)
        next_run=await self.store.create_run('org','campaign',1,self.scenes,'next',parent_run_id=run['id'])
        with self.assertRaises(WorkflowConflict):
            await self.store.recover('org',next_run['id'],key='recover',expected_revision=2)

    async def test_master_crossfade_duration_and_background_binding(self):
        run=await self.start(transitions=['crossfade'],background_asset_id='music:approved-v1')
        await self.pass_task((await self.store.claim())[0])
        await self.pass_task((await self.store.claim())[0])
        master=(await self.store.claim())[0]
        self.assertAlmostEqual(master['specification']['target_duration_sec'],3.85)
        self.assertEqual(master['specification']['background_asset_id'],'music:approved-v1')

    async def test_product_scope_persists_across_scene_and_master_tasks(self):
        run=await self.start(product_id='sku-record')
        first=(await self.store.claim())[0]
        self.assertEqual(first['product_id'],'sku-record')
        await self.pass_task(first)
        second=(await self.store.claim())[0]
        self.assertEqual(second['product_id'],'sku-record')
        await self.pass_task(second)
        self.assertEqual((await self.store.claim())[0]['product_id'],'sku-record')

    async def test_renderer_context_is_immutable_and_bound_to_tasks_and_tokens(self):
        context={'renderer':{'model':'configured-v1','assets':[{'sha256':'a'*64}]}}
        run=await self.start(reuse_context=context)
        context['renderer']['model']='caller-mutated'
        self.assertEqual(run['reuse_context']['renderer']['model'],'configured-v1')
        first=(await self.store.claim())[0]
        self.assertEqual(first['renderer_context'],run['reuse_context']['renderer'])
        self.assertEqual(first['scene_prompts'],self.scenes)
        verified=await self.pass_task(first)
        self.assertEqual(verified['scenes'][0]['verified']['reuse_context_hash'],run['reuse_context_hash'])
        with self.assertRaises(WorkflowConflict):
            await self.store._mutate('org',run['id'],lambda r:r['reuse_context']['renderer'].update(model='forged'))
        changed=await self.store.create_run('org','campaign',1,self.scenes,'renderer-update',parent_run_id=run['id'],
            reuse_context={'renderer':{'model':'configured-v2','assets':[{'sha256':'a'*64}]}})
        self.assertIsNone(changed['scenes'][0]['verified'])
