import unittest
import hashlib
import httpx
from unittest.mock import patch
from services.milo.director.provider import DirectorProvider
from services.milo.director.storyboard import content_hash
from test_milo_director_contracts import scene


class ProviderClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_replay_binding_and_actual_artifact_hash(self):
        task=dict(org_id='a',run_id='run',campaign_id='campaign',storyboard_revision=1,attempt=1,kind='scene',scene_index=1,
            spec_hash=content_hash(scene()),specification=scene(),idempotency_key='one',language='en')
        calls=[]; body=b'actual encoded artifact'
        async def server(request):
            calls.append(request)
            self.assertEqual(request.headers['Authorization'],'Bearer test-key')
            binding={k:v for k,v in DirectorProvider().envelope(task).items() if k in ('org_id','run_id','campaign_id','storyboard_revision','attempt','spec_sha256','idempotency_key')}
            if '/artifacts/' in request.url.path:return httpx.Response(200,content=body)
            result={'artifact_sha256':hashlib.sha256(body).hexdigest()}
            result['evidence_sha256']=content_hash(result)
            return httpx.Response(200,json={'task_id':'receipt','binding':binding,'status':'complete','result':result})
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client, self._env():
            provider=DirectorProvider(client)
            receipt=await provider.submit(task);task['receipt']=receipt
            self.assertEqual((await provider.reconcile(task))['task_id'],'receipt')
            self.assertEqual((await provider.poll(task))['status'],'completed')
            task['org_id']='foreign'
            with self.assertRaises(ValueError): provider.validate(task,receipt)
        self.assertEqual(len(calls),4)

    def _env(self):
        class Environment:
            async def __aenter__(self):self.patch=patch.dict('os.environ',{'MPT_API_KEY':'test-key','MONEYPRINTERTURBO_BASE_URL':'http://renderer'});self.patch.start()
            async def __aexit__(self,*args):self.patch.stop()
        return Environment()
