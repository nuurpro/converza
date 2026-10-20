"""Opt-in full API import gates using the focused renderer dependencies."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
import tempfile
from uuid import uuid4
from unittest.mock import patch


@unittest.skipUnless(os.getenv('MPT_RUN_API_TESTS') == '1', 'Opt-in provider API dependencies')
class MiloProviderApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(Path(__file__).parents[2]))
        os.environ['MPT_APPROVED_ONLY']='1'
        os.environ['PEXELS_API_KEY']='local-test-key'
        os.environ['MPT_API_KEY']='local-control-test-key'
        cls.folder=tempfile.TemporaryDirectory()
        os.environ['MPT_STATE_DB']=str(Path(cls.folder.name)/'renderer.sqlite3')
        from app.asgi import app
        from app.services import state as sm
        from app.services.sqlite_state import SQLiteState
        sm.state=SQLiteState(os.environ['MPT_STATE_DB'])
        from fastapi.testclient import TestClient
        cls.client=TestClient(app,headers={'Authorization':'Bearer local-control-test-key'})
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None,None,None);cls.client.close()
        from app.services import state as sm
        sm.state.stop_runtime();cls.folder.cleanup()

    def payload(self):
        scenes=[{'spoken_narration':'Exact words.','visual_broll_cues':'steel hinge','on_screen_text':'Line one\n\nLine two'}]
        content=json.dumps({'video_script':scenes,'language':'en'},sort_keys=True,ensure_ascii=False,separators=(',',':'))
        return {'video_subject':'test','video_script':'Exact words.','video_terms':['steel hinge'],
            'video_language':'en','approved_scenes':scenes,'milo_binding':{'job_id':'build','org_id':'brand','campaign_id':'campaign',
                'script_revision':1,'provider_attempt':1,'script_sha256':hashlib.sha256(content.encode()).hexdigest()}}

    def test_capabilities_and_generation_endpoints_refuse_unapproved_work(self):
        self.assertTrue(self.client.get('/api/v1/capabilities').json()['milo_job_binding_v1'])
        self.assertEqual(self.client.post('/api/v1/scripts',json={'video_subject':'write new narration'}).status_code,409)
        self.assertEqual(self.client.post('/api/v1/videos',json={'video_subject':'generate me'}).status_code,400)

    def test_bound_request_persists_binding_before_queuing(self):
        from app.controllers.v1.video import task_manager
        payload=self.payload()
        with patch.object(task_manager,'add_task') as queue:
            response=self.client.post('/api/v1/videos',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        queue.assert_called_once()
        task_id=response.json()['data']['task_id']
        receipt=self.client.get('/api/v1/tasks/'+task_id)
        self.assertEqual(receipt.json()['data']['milo_binding'],payload['milo_binding'])

    def test_invalid_binding_is_a_client_error_without_queuing(self):
        payload=self.payload(); payload['milo_binding']['script_sha256']='a'*64
        response=self.client.post('/api/v1/videos',json=payload)
        self.assertEqual(response.status_code,400,response.text)

    def test_control_requests_require_matching_bearer_key(self):
        for authorization in ['', 'Bearer wrong-key']:
            for method,url,body in [('GET','/api/v1/tasks',None),('GET','/api/v1/capabilities',None),
                    ('POST','/api/v1/videos',self.payload()),('DELETE','/api/v1/tasks/'+str(uuid4()),None)]:
                response=self.client.request(method,url,json=body,headers={'Authorization':authorization})
                self.assertEqual(response.status_code,401,response.text)
        with patch.dict(os.environ,{'MPT_API_KEY':''}):
            self.assertEqual(self.client.get('/api/v1/capabilities').status_code,503)

    def test_public_preview_exposes_only_uuid_video_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            task_id=str(uuid4())
            directory=Path(folder,task_id);directory.mkdir()
            (directory/'final-1.mp4').write_bytes(b'local-video-fixture')
            (directory/'script.json').write_text('private script',encoding='utf-8')
            with patch('app.asgi.task_dir',folder),patch('app.asgi.utils.task_dir') as create_directory:
                response=self.client.get('/tasks/'+task_id+'/final-1.mp4',headers={'Authorization':''})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(self.client.get('/tasks/'+task_id+'/script.json').status_code,404)
                unknown=str(uuid4())
                self.assertEqual(self.client.get('/tasks/'+unknown+'/final-1.mp4').status_code,404)
                self.assertFalse(Path(folder,unknown).exists())
                create_directory.assert_not_called()

    def test_public_preview_refuses_external_symlink(self):
        with tempfile.TemporaryDirectory() as folder,tempfile.TemporaryDirectory() as outside:
            task_id=str(uuid4());directory=Path(folder,task_id);directory.mkdir()
            target=Path(outside,'private.mp4');target.write_bytes(b'private-video')
            link=directory/'final-1.mp4'
            try:link.symlink_to(target)
            except OSError:
                # Exercise the same resolved-path boundary on hosts where
                # creating Windows symlinks requires unavailable privileges.
                realpath=os.path.realpath
                def resolved(value):
                    return str(target) if Path(value)==link else realpath(value)
                with patch('app.asgi.task_dir',folder),patch('app.asgi.file_security.os.path.realpath',side_effect=resolved):
                    self.assertEqual(self.client.get('/tasks/'+task_id+'/final-1.mp4').status_code,404)
            else:
                with patch('app.asgi.task_dir',folder):
                    self.assertEqual(self.client.get('/tasks/'+task_id+'/final-1.mp4').status_code,404)
