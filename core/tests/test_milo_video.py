import copy
import unittest
from unittest.mock import AsyncMock, patch

import httpx


class MiloVideoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env=patch.dict('os.environ',{'MPT_API_KEY':'test-control-key'})
        self.env.start();self.addCleanup(self.env.stop)

    def job(self):
        return {'id':'build-1','org_id':'brand','campaign_id':'campaign',
            'payload':{'language':'en','approved_revision':3,'video_script':[
                {'spoken_narration':'Does it last?', 'visual_broll_cues':'steel hinge closeup','on_screen_text':'Built to last'},
                {'spoken_narration':'See the test.', 'visual_broll_cues':'durability laboratory','on_screen_text':'Watch the test'}]}}

    async def render(self, job, handler, **kwargs):
        from services.milo.video import render_approved_script
        self.store = type('Store',(),{'update_build':AsyncMock()})()
        self.active_job=job
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await render_approved_script(job,self.store,client=client,**kwargs)

    def handler(self, request):
        import json
        self.requests.append(request)
        if request.url.path.endswith('/capabilities'):
            return httpx.Response(200,json={'approved_scenes_v1':True,'milo_job_binding_v1':True,
                'durable_state_v1':True,'control_api_auth_v1':True,'provider_attempt_binding_v1':True,
                'automatic_publishing_disabled_for_approved_scenes':True})
        if request.method=='POST':
            self.sent=json.loads(request.content)
            return httpx.Response(200,json={'data':{'task_id':'provider-1'}})
        from services.milo.video import build_binding
        return httpx.Response(200,json={'data':{'state':1,'videos':['/tasks/provider-1/final.mp4'],'milo_binding':build_binding(self.active_job)}})

    async def test_exact_approved_scenes_and_language_reach_provider_and_id_is_persisted(self):
        self.requests=[]
        job=self.job(); original=copy.deepcopy(job)
        result=await self.render(job,self.handler)
        self.assertEqual(self.sent['video_script'],'Does it last?\n\nSee the test.')
        self.assertEqual(self.sent['approved_scenes'],original['payload']['video_script'])
        self.assertEqual(self.sent['video_terms'],['steel hinge closeup','durability laboratory'])
        self.assertEqual(self.sent['font_name'],'DejaVuSans.ttf')
        from services.milo.video import build_binding
        self.assertEqual(self.sent['milo_binding'],build_binding(job))
        self.assertEqual(result['approved_script'],original['payload']['video_script'])
        calls=self.store.update_build.await_args_list
        self.assertEqual(calls[0].args[1]['submission_state'],'submission_started')
        self.assertEqual(calls[1].args[1]['provider_task_id'],'provider-1')
        self.assertEqual(result['task_id'],'provider-1')
        self.assertTrue(all(request.headers.get('Authorization')=='Bearer test-control-key' for request in self.requests))
        self.assertTrue(result['video_url'].endswith('/tasks/provider-1/final.mp4'))

    async def test_supported_languages_use_documented_voices(self):
        for language,voice in [('en','en-US-AriaNeural'),('ru','ru-RU-SvetlanaNeural'),('uz','uz-UZ-MadinaNeural')]:
            self.requests=[]; job=self.job(); job['payload']['language']=language
            await self.render(job,self.handler)
            self.assertEqual(self.sent['voice_name'],voice)

    async def test_retry_polls_persisted_task_without_another_submission(self):
        self.requests=[]; job=self.job(); job['provider_task_id']='provider-1'
        await self.render(job,self.handler)
        self.assertEqual([r.method for r in self.requests],['GET'])
        self.store.update_build.assert_not_awaited()

    async def test_store_payload_task_id_is_resumed_without_resubmission(self):
        self.requests=[]; job=self.job(); job['payload']['provider_task_id']='provider-1'
        await self.render(job,self.handler)
        self.assertEqual([r.method for r in self.requests],['GET'])

    async def test_store_payload_ambiguous_state_is_never_resubmitted(self):
        from services.milo.video import SubmissionUncertain
        self.requests=[]; job=self.job(); job['payload']['submission_state']='ambiguous'
        with self.assertRaises(SubmissionUncertain):await self.render(job,self.handler)
        self.assertEqual(self.requests,[])

    async def test_ambiguous_creation_is_persisted_and_never_resubmitted(self):
        self.requests=[]
        def fail(request):
            if request.method=='POST':
                raise httpx.ReadTimeout('lost create response',request=request)
            return self.handler(request)
        from services.milo.video import SubmissionUncertain
        job=self.job()
        with self.assertRaises(SubmissionUncertain): await self.render(job,fail)
        self.assertEqual(self.store.update_build.await_args_list[-1].args[1]['submission_state'],'ambiguous')
        job['submission_state']='ambiguous'; self.requests=[]
        with self.assertRaises(SubmissionUncertain): await self.render(job,self.handler)
        self.assertEqual(self.requests,[])

    async def test_started_without_id_requires_reconciliation(self):
        from services.milo.video import SubmissionUncertain
        job=self.job(); job['submission_state']='submission_started'; self.requests=[]
        with self.assertRaises(SubmissionUncertain): await self.render(job,self.handler)
        self.assertEqual(self.requests,[])

    async def test_old_provider_is_rejected_before_submission(self):
        self.requests=[]
        def old(request):
            self.requests.append(request)
            return httpx.Response(404,json={})
        with self.assertRaisesRegex(RuntimeError,'approved scene'):
            await self.render(self.job(),old)
        self.assertFalse(any(r.method=='POST' for r in self.requests))
        self.store.update_build.assert_not_awaited()

    async def test_malformed_creation_is_ambiguous(self):
        self.requests=[]
        def malformed(request):
            if request.method=='POST': return httpx.Response(200,json={'data':{}})
            return self.handler(request)
        from services.milo.video import SubmissionUncertain
        with self.assertRaises(SubmissionUncertain): await self.render(self.job(),malformed)
        self.assertEqual(self.store.update_build.await_args_list[-1].args[1]['submission_state'],'ambiguous')

    async def test_provider_failure_does_not_report_video(self):
        self.requests=[]; job=self.job(); job['provider_task_id']='provider-1'
        from services.milo.video import build_binding,ProviderRenderFailed
        with self.assertRaises(ProviderRenderFailed):
            await self.render(job,lambda request:httpx.Response(200,json={'data':{'state':-1,'milo_binding':build_binding(job)}}))
        self.assertEqual(self.store.update_build.await_args_list[-1].args[1]['submission_state'],'provider_failed')

    async def test_attempt_binding_rejects_receipt_from_before_explicit_retry(self):
        from services.milo.video import build_binding,validate_provider_receipt
        job=self.job();binding=build_binding(job);job['payload']['provider_attempt']=2
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':{'state':1,'milo_binding':binding}}))) as client:
            with self.assertRaisesRegex(RuntimeError,'binding'):await validate_provider_receipt(job,'task-1',client=client)

    async def test_missing_control_key_blocks_requests_without_anonymous_fallback(self):
        self.requests=[]
        with patch.dict('os.environ',{'MPT_API_KEY':''}):
            with self.assertRaisesRegex(RuntimeError,'MPT_API_KEY'):await self.render(self.job(),self.handler)
        self.assertEqual(self.requests,[])

    async def test_poll_timeout_keeps_existing_task_id(self):
        self.requests=[]; job=self.job(); job['provider_task_id']='provider-1'
        with self.assertRaises(TimeoutError):
            await self.render(job,self.handler,timeout_seconds=0)
        self.store.update_build.assert_not_awaited()

    async def test_completed_receipt_cannot_attach_another_brands_video(self):
        job=self.job(); job['payload']['provider_task_id']='foreign-task'
        from services.milo.video import build_binding
        binding={**build_binding(job),'org_id':'different-brand'}
        with self.assertRaisesRegex(RuntimeError,'binding'):
            await self.render(job,lambda request:httpx.Response(200,json={'data':{'state':1,'videos':['/secret.mp4'],'milo_binding':binding}}))

    async def test_completed_legacy_task_without_binding_is_blocked(self):
        job=self.job(); job['payload']['provider_task_id']='legacy-task'
        with self.assertRaisesRegex(RuntimeError,'binding'):
            await self.render(job,lambda request:httpx.Response(200,json={'data':{'state':1,'videos':['/legacy.mp4']}}))

    async def test_reconciliation_checks_exact_immutable_script_binding(self):
        from services.milo.video import build_binding,validate_provider_receipt
        job=self.job(); binding=build_binding(job)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':{'state':4,'milo_binding':binding}}))) as client:
            await validate_provider_receipt(job,'task-1',client=client)
            for field,value in [('org_id','other'),('id','other'),('campaign_id','other')]:
                changed={**job,field:value}
                with self.assertRaisesRegex(RuntimeError,'binding'):await validate_provider_receipt(changed,'task-1',client=client)
            changed=copy.deepcopy(job); changed['payload']['video_script'][0]['on_screen_text']='Changed overlay'
            with self.assertRaisesRegex(RuntimeError,'binding'):await validate_provider_receipt(changed,'task-1',client=client)
            changed=copy.deepcopy(job); changed['payload']['language']='uz'
            with self.assertRaisesRegex(RuntimeError,'binding'):await validate_provider_receipt(changed,'task-1',client=client)

    async def test_public_url_rewrites_provider_outputs_and_preserves_external_storage(self):
        from services.milo.video import build_binding
        for value,expected in [('/tasks/final.mp4','https://video.example/vea/tasks/final.mp4'),
            ('http://vea-renderer:8080/tasks/final.mp4?download=1','https://video.example/vea/tasks/final.mp4?download=1'),
            ('https://storage.example/final.mp4?token=abc','https://storage.example/final.mp4?token=abc')]:
            job=self.job(); job['payload']['provider_task_id']='task-1'
            binding=build_binding(job)
            with patch.dict('os.environ',{'MONEYPRINTERTURBO_BASE_URL':'http://vea-renderer:8080',
                    'MONEYPRINTERTURBO_PUBLIC_BASE_URL':'https://video.example/vea'}):
                result=await self.render(job,lambda request:httpx.Response(200,json={'data':{'state':1,'videos':[value],'milo_binding':binding}}))
            self.assertEqual(result['video_url'],expected)
