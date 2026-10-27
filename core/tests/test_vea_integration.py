"""VEA boundary regressions: approved-only entry and bound preset receipts."""
import copy
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

import test_milo_video as milo_tests


class VeaProviderTests(unittest.IsolatedAsyncioTestCase):
    setUp = milo_tests.MiloVideoTests.setUp
    job = milo_tests.MiloVideoTests.job
    handler = milo_tests.MiloVideoTests.handler
    render = milo_tests.MiloVideoTests.render
    def configured_job(self):
        job = self.job()
        job['payload']['vea_config'] = {
            'schema_version': 1, 'preset_id': 'high_velocity_d2c', 'variant_id': 'variant-1',
            'variant_revision': 1, 'product_id': None,
            'brand_snapshot': {'revision': 4, 'hex_colors': ['#112233']},
            'clip_overrides': [],
        }
        return job

    async def test_preset_configuration_is_forwarded_and_immutable_in_binding(self):
        from services.milo.video import _provider_payload, build_binding
        job = self.configured_job()
        payload = _provider_payload(job)
        self.assertEqual(payload.get('vea_config'), job['payload']['vea_config'])
        original = build_binding(job)
        changed = copy.deepcopy(job)
        changed['payload']['vea_config']['preset_id'] = 'editorial_showcase'
        self.assertNotEqual(original, build_binding(changed))

    async def test_legacy_provider_cannot_accept_a_preset_job(self):
        self.requests = []
        with self.assertRaisesRegex(RuntimeError, 'preset'):
            await self.render(self.configured_job(), self.handler)
        self.assertFalse(any(r.method == 'POST' for r in self.requests))

    async def test_missing_structured_artifact_rejects_completed_preset_job(self):
        job = self.configured_job()
        job['payload']['provider_task_id'] = 'provider-1'
        self.requests = []
        with self.assertRaisesRegex(RuntimeError, 'artifact'):
            await self.render(job, self.handler)

    async def test_renderer_relative_media_and_private_manifest_cross_boundary(self):
        from services.milo.video import build_binding
        job = self.configured_job()
        job['payload']['provider_task_id'] = 'provider-1'
        manifest = {'segments':[{'segment_id':'s0','asset_id':'clip','start_ms':0,'end_ms':2500}]}
        artifact = {'schema_version':1,'id':'variant-1','variant_revision':1,
                    'video_url':'/tasks/provider-1/final-1.mp4','thumbnail_url':'/tasks/provider-1/final-1.jpg',
                    'duration_sec':2.5,'preset_used':'high_velocity_d2c','preset_version':1,
                    'preset_sha256':'a'*64,'source_milo_script_id':'campaign','approved_script_revision':3,
                    'composition_sha256':'b'*64,'render_telemetry':{},'composition_manifest':manifest,'org_id':'brand'}
        def handler(request):
            return httpx.Response(200,json={'data':{'state':1,'videos':[artifact['video_url']],
                'milo_binding':build_binding(job),'vea_artifact':artifact}})
        result = await self.render(job,handler)
        self.assertTrue(result['vea_artifact']['video_url'].startswith('http'))
        self.assertEqual(result['composition_manifest'], manifest)
        self.assertNotIn('composition_manifest',result['vea_artifact'])

    async def test_failed_preset_receipt_preserves_actionable_error(self):
        from services.milo.video import build_binding, ProviderRenderFailed
        job = self.configured_job();job['payload']['provider_task_id'] = 'provider-1'
        def handler(request):
            return httpx.Response(200,json={'data':{'state':-1,'milo_binding':build_binding(job),
                'error_code':'missing_assets','error_message':'Add rights-confirmed product clips to the catalog.'}})
        with self.assertRaises(ProviderRenderFailed):
            await self.render(job,handler)
        values=self.store.update_build.await_args_list[-1].args[1]
        self.assertEqual(values.get('render_error_code'),'missing_assets')
        self.assertIn('rights-confirmed',values.get('render_error',''))

    async def test_recipe_is_pinned_durably_before_submission_and_receipt_matches(self):
        from services.milo.video import build_binding
        job=self.configured_job();requests=[]
        def handler(request):
            requests.append(request)
            if request.url.path.endswith('/capabilities'):
                response=self.handler(request).json();response['deterministic_presets_v1']=True
                return httpx.Response(200,json=response)
            if request.url.path.endswith('/vea/presets'):
                return httpx.Response(200,json={'data':{'presets':[{'id':'high_velocity_d2c','version':2,'sha256':'c'*64}]}})
            if request.method=='POST':
                sent=json.loads(request.content)
                self.assertEqual(sent['vea_config']['preset_sha256'],'c'*64)
                self.assertEqual(sent['vea_config']['preset_version'],2)
                return httpx.Response(200,json={'data':{'task_id':'pinned-task'}})
            artifact={'schema_version':1,'id':'variant-1','variant_revision':1,'video_url':'/tasks/pinned-task/final-1.mp4',
                'thumbnail_url':'/tasks/pinned-task/final-1.jpg','duration_sec':3,'preset_used':'high_velocity_d2c',
                'preset_version':2,'preset_sha256':'c'*64,'source_milo_script_id':'campaign','approved_script_revision':3,
                'composition_sha256':'b'*64,'render_telemetry':{}}
            return httpx.Response(200,json={'data':{'state':1,'videos':[artifact['video_url']],
                'milo_binding':build_binding(job),'vea_artifact':artifact,'composition_manifest':{'segments':[]}}})
        self.requests=[]
        result=await self.render(job,handler)
        self.assertEqual(result['vea_artifact']['preset_version'],2)
        self.assertEqual(self.store.update_build.await_args_list[0].args[1]['vea_config']['preset_sha256'],'c'*64)
        self.assertEqual([r.method for r in requests],['GET','GET','POST','GET'])

    async def test_legacy_submitting_state_never_resubmits(self):
        from services.milo.video import SubmissionUncertain
        job=self.job();job['payload']['submission_state']='submitting';self.requests=[]
        with self.assertRaises(SubmissionUncertain):
            await self.render(job,self.handler)
        self.assertEqual(self.requests,[])

    async def test_legacy_task_id_receipt_alias_resumes_polling(self):
        job=self.job();job['payload'].update(task_id='provider-1',submission_state='submitted');self.requests=[]
        await self.render(job,self.handler)
        self.assertEqual([r.method for r in self.requests],['GET'])


class VeaApprovedEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_video_request_does_not_generate_or_render_a_script(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import handle_direct_agent_message
        repo = InMemoryRepository()
        repo.seed_brand_passport('org', {'brand_name': 'Test'})
        with patch('lib.switchboard.classify_output', AsyncMock(return_value='customer_copy')), \
             patch('lib.switchboard.call_engine', AsyncMock(return_value='Unapproved words')) as engine, \
             patch('services.milo.worker.render_approved_script', AsyncMock(return_value={'video_url': 'bad'})) as renderer:
            result = await handle_direct_agent_message(org_id='org', agent_slug='vea', text='Render a new ad', repo=repo)
        engine.assert_not_awaited()
        renderer.assert_not_awaited()
        self.assertIn('approved', result['response'].lower())
        self.assertEqual(repo.drafts, [])


class VeaReviewStateTests(unittest.IsolatedAsyncioTestCase):
    def test_structured_video_cannot_be_text_edited_or_published(self):
        from services.workflow.state import apply_transition, WorkflowConflict
        for action in ('edit', 'begin_delivery', 'publish'):
            row = {'id':'v', 'revision':2, 'status':'AWAITING_HITL' if action=='edit' else 'APPROVED',
                   'vea_artifact':{'id':'variant'}, 'draft_content':'{}'}
            with self.subTest(action=action), self.assertRaises(WorkflowConflict):
                apply_transition(row, action, edited_content='changed', receipt={'channel':'telegram','message_id':1,'attempt_id':'a'})

    def test_superseded_video_cannot_be_approved(self):
        from services.workflow.state import apply_transition, WorkflowConflict
        with self.assertRaises(WorkflowConflict):
            apply_transition({'id':'v','revision':2,'status':'AWAITING_HITL','draft_content':'{}','vea_artifact':{'id':'v'},'superseded_by':'new'}, 'approve')

    async def test_legacy_vea_generation_retry_cannot_bypass_script_approval(self):
        from lib.repository import InMemoryRepository
        from lib.switchboard import run_agent
        from services.workflow.state import WorkflowConflict
        repo = InMemoryRepository()
        repo.seed_brand_passport('org', {'brand_name': 'Test'})
        draft = await repo.create_draft('org', 'vea', 'old request', '')
        with patch('lib.switchboard.call_engine', AsyncMock(return_value='')) as engine:
            with self.assertRaisesRegex(WorkflowConflict, 'approved'):
                await run_agent(org_id='org', agent_slug='vea', text='retry', triggered_by='owner', repo=repo, existing_draft=draft)
        engine.assert_not_awaited()


class VeaReviewRouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from lib.repository import InMemoryRepository
        from lib.workflow_routes import create_workflow_router
        from test_workflow_routes import authenticate, owner
        self.repo = InMemoryRepository()
        async def seed():
            draft = await self.repo.create_draft('org-a','vea','Approved video','')
            return await self.repo.transition_draft('org-a',draft['id'],'ready',1,'ready',edited_content='video artifact')
        self.draft=asyncio.run(seed())
        self.repo.drafts[0]['vea_artifact']={'id':'variant'}
        app=FastAPI();app.include_router(create_workflow_router(lambda:self.repo,authenticate,owner))
        self.client=TestClient(app)
        self.addCleanup(self.client.close)

    def decide(self,action):
        return self.client.post(f'/api/hitl/{self.draft["id"]}/{action}',
            headers={'authorization':'Bearer user-a','idempotency-key':'approve-video'},
            json={'expected_revision':2,'final_content':'changed'})

    def test_approval_revalidates_once_and_committed_retry_replays(self):
        with patch('services.vea.store.validate_review',AsyncMock()) as validate:
            response=self.decide('approve')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.decide('approve').json(),response.json())
        validate.assert_awaited_once()
        self.assertEqual(response.json()['status'],'APPROVED')

    def test_stale_evidence_prevents_approval(self):
        from services.workflow.state import WorkflowConflict
        with patch('services.vea.store.validate_review',AsyncMock(side_effect=WorkflowConflict('Brand changed'))):
            self.assertEqual(self.decide('approve').status_code,409)
        self.assertEqual(self.repo.drafts[0]['status'],'AWAITING_HITL')

    def test_unavailable_asset_catalog_is_an_actionable_service_failure(self):
        with patch('services.vea.store.validate_review',AsyncMock(side_effect=httpx.ConnectError('unavailable'))):
            self.assertEqual(self.decide('approve').status_code,503)

    def test_generic_text_edit_of_video_is_rejected(self):
        self.assertEqual(self.decide('edit').status_code,409)
