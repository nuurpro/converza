"""Opt-in real ASGI/FFmpeg integration with locally synthesized test inputs.

Provider speech and ASR are replaced at their boundary; HTTP auth, approved
contracts, durable receipts, asset checks, composition, codecs and previews run.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.getenv('MPT_RUN_API_TESTS') == '1', 'Opt-in full API dependencies')
class VeaApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update(MPT_APPROVED_ONLY='1', MPT_API_KEY='local-vea-test-key', VEA_ENABLED='1')
        cls.folder = tempfile.TemporaryDirectory(); cls.root = Path(cls.folder.name)
        os.environ['MPT_STATE_DB'] = str(cls.root/'state.sqlite3')
        from app.asgi import app
        from app.services import state as sm
        from app.services.sqlite_state import SQLiteState
        sm.state = SQLiteState(os.environ['MPT_STATE_DB'])
        from fastapi.testclient import TestClient
        cls.client = TestClient(app, headers={'Authorization': 'Bearer local-vea-test-key'})
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None); cls.client.close()
        from app.services import state as sm
        sm.state.stop_runtime(); cls.folder.cleanup()

    def test_presets_assets_auth_and_full_bound_render(self):
        from app.services import vea
        from app.controllers.v1.video import task_manager
        from test.services.test_vea_contract import VeaContractTests
        root = self.root
        vea.run_media(['-f', 'lavfi', '-i', 'color=c=navy:s=180x320:r=30:d=2',
                       '-c:v', 'libx264', '-pix_fmt', 'yuv420p', root/'clip.mp4'])
        vea.run_media(['-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', 'libmp3lame', root/'voice.mp3'])
        asset = {'id': 'clip', 'kind': 'video', 'org_id': 'org', 'path': 'clip.mp4',
                 'sha256': vea.file_hash(root/'clip.mp4'), 'duration_sec': 2, 'width': 180, 'height': 320,
                 'tags': {'en': ['steel hinge']}, 'product_ids': [], 'rights_confirmed': True, 'permitted_uses': ['advertising']}
        (root/'catalog.json').write_text(json.dumps({'schema_version': 1, 'assets': [asset]}))
        for endpoint in ['/api/v1/vea/presets', '/api/v1/vea/assets?org_id=org']:
            self.assertEqual(self.client.get(endpoint, headers={'Authorization': ''}).status_code, 401)
        self.assertEqual(len(self.client.get('/api/v1/vea/presets').json()['data']['presets']), 2)
        payload = VeaContractTests().payload()
        preset = vea.load_preset('high_velocity_d2c')
        payload['vea_config'].update(preset_version=preset['version'], preset_sha256=vea.content_hash(preset))
        payload['milo_binding']['vea_config_sha256'] = vea.content_hash(payload['vea_config'])
        duration = vea.media_duration(root/'voice.mp3')
        speech = {'path': root/'voice.mp3', 'cache_key': 'a'*64, 'provider': 'fixture', 'fallback_used': False}
        alignment = vea.align_words('Exact words.', [{'word': 'Exact', 'start_ms': 20, 'end_ms': 400},
                                    {'word': 'words.', 'start_ms': 420, 'end_ms': 900}], round(duration*1000))
        with patch.dict(os.environ, {'VEA_ASSET_ROOT': str(root)}):
            available = self.client.get('/api/v1/vea/assets?org_id=org').json()['data']['assets']
            self.assertEqual(available[0]['id'], 'clip'); self.assertNotIn('path', available[0])
            self.assertEqual(self.client.get('/api/v1/vea/assets?org_id=other').json()['data']['assets'], [])
            with patch.object(task_manager, 'add_task') as queue:
                response = self.client.post('/api/v1/videos', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            task_id = response.json()['data']['task_id']
            with patch.object(vea, 'synthesize_narration', return_value=speech) as synthesize, patch.object(vea, 'extract_word_timestamps', return_value=alignment):
                queue.call_args.args[0](**queue.call_args.kwargs)
                self.assertIsNone(synthesize.call_args.args[1])
        receipt = self.client.get('/api/v1/tasks/' + task_id).json()['data']
        self.assertEqual(receipt['state'], 1, receipt)
        self.assertEqual(receipt['milo_binding']['vea_config_sha256'], payload['milo_binding']['vea_config_sha256'])
        artifact = receipt['vea_artifact']
        self.assertEqual(artifact['source_milo_script_id'], 'campaign')
        self.assertEqual(artifact['composition_sha256'], vea.content_hash(receipt['composition_manifest']))
        self.assertEqual(self.client.get(artifact['video_url']).status_code, 200)
        preview = self.client.get(artifact['thumbnail_url'], headers={'Authorization': ''})
        self.assertEqual(preview.status_code, 200); self.assertEqual(preview.headers['content-type'], 'image/jpeg')
        self.assertEqual(self.client.get(f'/tasks/{task_id}/composition.json').status_code, 404)

    def test_failed_vea_receipt_records_actionable_safe_failure(self):
        from app.services import task, vea
        from app.models.schema import TaskVideoRequest
        from app.services import state as sm
        from test.services.test_vea_contract import VeaContractTests
        params = TaskVideoRequest(**VeaContractTests().payload())
        task_id = 'vea-failure'
        with patch.object(vea, 'start_render', side_effect=vea.VeaError('missing_assets', 'Seed matching rights-cleared clips')):
            task.start(task_id, params)
        receipt = sm.state.get_task(task_id)
        self.assertEqual(receipt['state'], -1)
        self.assertEqual(receipt['error_code'], 'missing_assets')
        self.assertEqual(receipt['error_message'], 'Seed matching rights-cleared clips')
        self.assertEqual(receipt['render_telemetry']['failure_code'], 'missing_assets')


if __name__ == '__main__': unittest.main()
