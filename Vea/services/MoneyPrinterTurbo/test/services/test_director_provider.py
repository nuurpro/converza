import json
from pathlib import Path
import sys
import tempfile
import unittest
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import vea


def payload():
    scene = {'scene_index': 1, 'total_scenes': 1, 'target_duration_sec': 2.0,
             'narration_chunk': 'Exact narration.',
             'visual_directive': {'prompt': 'hinge', 'subject_action': 'turn', 'camera_movement': 'static', 'lighting_style': 'soft'},
             'asset_constraints': {'required_sku_tags': ['sku-1'], 'brand_hex_palette': ['#ffffff'], 'negative_visual_constraints': []},
             'overlay_text': {'text': 'Exact overlay', 'font_family': 'Arial', 'font_size': 58, 'color': '#ffffff',
                              'position': 'center', 'animation': 'none', 'start_sec': 0.0, 'end_sec': 2.0}}
    return {'org_id': 'org', 'run_id': 'run', 'campaign_id': 'campaign', 'storyboard_revision': 1,
            'attempt': 1, 'spec_sha256': vea.content_hash(scene), 'idempotency_key': 'key', 'scene': scene}


class DirectorProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (Path(__file__).resolve().parents[2] / 'storage').mkdir(exist_ok=True)

    def test_campaign_barrier_serializes_competing_runs_and_preserves_replay(self):
        from app.services.director import ReceiptStore, Conflict
        from concurrent.futures import ThreadPoolExecutor
        import threading
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            store = ReceiptStore(Path(folder) / 'jobs.sqlite3')
            gate = threading.Barrier(2)
            requests = [payload(), payload()]
            requests[1].update(run_id='new-run', storyboard_revision=2, idempotency_key='new-key')
            def submit(request):
                gate.wait()
                try: return store.submit('scene', request)
                except Conflict as exc: return str(exc)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(submit, requests))
            accepted = [r for r in results if isinstance(r, dict)]
            self.assertEqual(len(accepted), 1)
            self.assertEqual([r for r in results if isinstance(r, str)], ['campaign_execution_busy'])
            winner = next(r for r, result in zip(requests, results) if isinstance(result, dict))
            loser = next(r for r, result in zip(requests, results) if isinstance(result, str))
            self.assertEqual(store.submit('scene', winner)['task_id'], accepted[0]['task_id'])
            claimed = store.claim(accepted[0]['task_id'])
            with self.assertRaisesRegex(Conflict, 'campaign_execution_busy'): store.submit('scene', loser)
            store.finish(claimed['task_id'], claimed['fence'], result={'done': True})
            self.assertEqual(store.submit('scene', loser)['status'], 'queued')

    def test_context_mismatch_blocks_execution_and_context_is_stamped(self):
        from app.services import director
        from unittest.mock import patch
        actual = {'asset_catalog_sha256': 'a'*64, 'renderer_config_sha256': 'b'*64}
        expected = {**actual, 'renderer_config_sha256': 'c'*64}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            receipts = director.ReceiptStore(Path(folder) / 'jobs.sqlite3')
            first = payload(); first['expected_context'] = expected
            job = receipts.submit('scene', first)
            with patch('app.services.director.store', return_value=receipts), patch('app.services.director.rendering_context', return_value=actual), patch('app.services.director.render_scene') as render:
                director.execute(job['task_id'])
                render.assert_not_called()
            failed = receipts.get(job['task_id'], 'org')
            self.assertEqual(failed['status'], 'failed')
            self.assertEqual(failed['error']['code'], 'renderer_context_changed')
            second = payload(); second.update(attempt=2, idempotency_key='attempt-two', expected_context=actual)
            job = receipts.submit('scene', second)
            with patch.dict(os.environ, {'VEA_DIRECTOR_ROOT': folder}), patch('app.services.director.store', return_value=receipts), patch('app.services.director.rendering_context', return_value=actual), patch('app.services.director.render_scene', return_value={'artifact_sha256': 'd'*64}):
                director.execute(job['task_id'])
            self.assertEqual(receipts.get(job['task_id'], 'org')['result']['renderer_context'], actual)

    def test_competing_campaign_http_posts_accept_one_and_allow_exact_replay(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.controllers.v1.director import router
        from app.services.director import ReceiptStore
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        import threading
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            receipts = ReceiptStore(Path(folder) / 'jobs.sqlite3')
            app = FastAPI(); app.include_router(router)
            requests = [payload(), payload()]
            requests[1].update(run_id='new-run', storyboard_revision=2, idempotency_key='new-key')
            gate = threading.Barrier(2)
            with patch.dict(os.environ, {'MPT_API_KEY': 'test-key'}), patch('app.services.director.store', return_value=receipts), patch('app.services.director.execute'):
                def post(request):
                    with TestClient(app, headers={'Authorization': 'Bearer test-key'}) as client:
                        gate.wait()
                        return client.post('/api/v1/director/scenes', json=request)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    responses = list(pool.map(post, requests))
                self.assertEqual(sorted(r.status_code for r in responses), [202, 409])
                winner = next(request for request, response in zip(requests, responses) if response.status_code == 202)
                accepted = next(response.json() for response in responses if response.status_code == 202)
                with TestClient(app, headers={'Authorization': 'Bearer test-key'}) as client:
                    replay = client.post('/api/v1/director/scenes', json=winner)
                self.assertEqual(replay.status_code, 202)
                self.assertEqual(replay.json()['task_id'], accepted['task_id'])

    def test_concurrent_duplicate_submissions_have_one_durable_receipt(self):
        from app.services.director import ReceiptStore
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            store = ReceiptStore(Path(folder) / 'jobs.sqlite3')
            with ThreadPoolExecutor(max_workers=8) as pool:
                receipts = list(pool.map(lambda _: store.submit('scene', payload()), range(8)))
            self.assertEqual(len({r['task_id'] for r in receipts}), 1)

    def test_expired_running_receipt_blocks_uncertain_rerender(self):
        from app.services.director import ReceiptStore
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            store = ReceiptStore(Path(folder) / 'jobs.sqlite3')
            job = store.submit('scene', payload()); store.claim(job['task_id'])
            with store.connect() as db:
                db.execute('UPDATE director_jobs SET lease=0 WHERE task_id=?', (job['task_id'],))
            store.recover()
            self.assertEqual(store.get(job['task_id'], 'org')['status'], 'failed')
            self.assertIsNone(store.claim(job['task_id']))

    def test_physical_speech_regions_preserve_offsets_and_short_in_word_pauses(self):
        samples = [0.0]*1600 + [.1]*3200 + [0.0]*1600 + [.1]*3200 + [0.0]*8000 + [.1]*3200 + [0.0]*1600
        regions = vea.speech_regions(samples)
        self.assertEqual(regions, [(1280, 9920), (17280, 21120)])

    @unittest.skipUnless(os.getenv('VEA_TESSERACT'), 'Opt-in actual local OCR executable/language packs')
    def test_actual_multilingual_ocr_of_encoded_frames(self):
        from app.services import director
        import shutil
        for language, text in [('en', 'Perfect fit'), ('ru', 'Точный текст'), ('uz', 'Aniq matn')]:
            with self.subTest(language=language), tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
                root = Path(folder)
                shutil.copyfile('C:/Windows/Fonts/arial.ttf', root / 'font.ttf')
                (root / 'text.txt').write_text(text, encoding='utf-8')
                vea.run_media(['-f', 'lavfi', '-i', 'color=c=0x20304f:s=1080x1920:r=30:d=2', '-vf',
                               'drawtext=fontfile=font.ttf:textfile=text.txt:fontcolor=white:fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2',
                               '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-pix_fmt', 'yuv420p', 'video.mp4'], cwd=root)
                overlay = director.Overlay(text=text, font_family='Arial', font_size=64, color='#FFFFFF', position='center', animation='none', start_sec=0, end_sec=2)
                rows = director.ocr_frames(root / 'video.mp4', overlay, language, root)
                self.assertEqual(len(rows), 3)
                self.assertTrue(all(row['observed_text'] == text for row in rows), rows)

    def test_synthetic_master_ffmpeg_preserves_order_and_measures_encoded_audio(self):
        """Real media plumbing; mocked OCR/Whisper do not establish gate accuracy."""
        from app.services import director
        from unittest.mock import patch
        import os
        import shutil
        if not shutil.which('ffmpeg'): self.skipTest('Local FFmpeg required')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            root = Path(folder)
            receipts = director.ReceiptStore(root / 'jobs.sqlite3')
            with patch.dict(os.environ, {'VEA_DIRECTOR_ROOT': str(root / 'artifacts')}), patch('app.services.director.store', return_value=receipts):
                scene_job = receipts.submit('scene', payload())
                claimed = receipts.claim(scene_job['task_id'])
                destination = director.artifact_dir(scene_job['task_id']); destination.mkdir(parents=True)
                vea.run_media(['-f', 'lavfi', '-i', 'color=c=blue:s=1080x1920:r=30:d=2', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                               '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', destination / 'final-1.mp4'])
                vea.run_media(['-i', destination / 'final-1.mp4', '-vn', '-ar', '48000', '-ac', '2', destination / 'narration.wav'])
                digest = vea.file_hash(destination / 'final-1.mp4')
                receipts.finish(scene_job['task_id'], claimed['fence'], result={'scene_index': 1, 'artifact_sha256': digest,
                    'media': director.media_evidence(destination / 'final-1.mp4'), 'overlay_timeline': [payload()['scene']['overlay_text']], 'ocr': []})
                manifest = director.Manifest(storyboard_revision=1, scenes=[director.SceneToken(scene_index=1, task_id=scene_job['task_id'], artifact_sha256=digest, verified_token='root-verified')], target_duration_sec=2)
                request = {k: v for k, v in payload().items() if k != 'scene'}
                request.update(idempotency_key='master', manifest=manifest.model_dump(mode='json'), spec_sha256=vea.content_hash(manifest.model_dump(mode='json')))
                master = receipts.submit('master', request)
                with patch('app.services.director.ocr_frames', return_value=[]), patch('app.services.director.observe_words', return_value=[]), patch('app.services.director.vea.ROOT', root):
                    result = director.assemble_master(master)
                self.assertEqual(result['ordered_scenes'][0]['artifact_sha256'], digest)
                self.assertEqual(result['audio']['clipped_samples'], 0)
                self.assertTrue(result['media']['decoded'])
                self.assertLess(abs(result['media']['duration_sec'] - 2), .15)
                self.assertTrue((root / 'storage/tasks' / master['task_id'] / 'final-1.mp4').is_file())

    def test_durable_receipts_bind_entire_request_and_tenant(self):
        from app.services.director import ReceiptStore, Conflict
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            path = Path(folder) / 'jobs.sqlite3'
            store = ReceiptStore(path)
            first = store.submit('scene', payload())
            self.assertEqual(first, ReceiptStore(path).submit('scene', payload()))
            changed = payload(); changed['attempt'] = 2
            with self.assertRaises(Conflict): store.submit('scene', changed)
            self.assertIsNone(store.get(first['task_id'], 'another-org'))
            self.assertEqual(store.get(first['task_id'], 'org')['status'], 'queued')

    def test_claim_is_exclusive_and_terminal_result_is_immutable(self):
        from app.services.director import ReceiptStore
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            store = ReceiptStore(Path(folder) / 'jobs.sqlite3')
            job = store.submit('scene', payload())
            claim = store.claim(job['task_id'])
            self.assertIsNotNone(claim)
            self.assertIsNone(store.claim(job['task_id']))
            self.assertTrue(store.finish(job['task_id'], claim['fence'], result={'sha256': 'x'}))
            self.assertFalse(store.finish(job['task_id'], claim['fence'], result={'sha256': 'y'}))
            self.assertEqual(store.get(job['task_id'], 'org')['result'], {'sha256': 'x'})

    def test_scene_validates_hash_timing_and_extra_fields(self):
        from app.services.director import SceneRequest
        from pydantic import ValidationError
        SceneRequest.model_validate(payload())
        bad = payload(); bad['scene']['overlay_text']['end_sec'] = 3
        with self.assertRaises(ValidationError): SceneRequest.model_validate(bad)
        bad = payload(); bad['spec_sha256'] = '0' * 64
        with self.assertRaises(ValidationError): SceneRequest.model_validate(bad)
        bad = payload(); bad['scene']['unexpected'] = True
        with self.assertRaises(ValidationError): SceneRequest.model_validate(bad)

    def test_integer_json_times_preserve_approved_spec_hash(self):
        from app.services.director import SceneRequest
        raw = payload()
        raw['scene']['overlay_text']['start_sec'] = 0
        raw['scene']['overlay_text']['end_sec'] = 2
        raw['spec_sha256'] = vea.content_hash(raw['scene'])
        validated = SceneRequest.model_validate(raw)
        self.assertEqual(validated.spec_sha256, raw['spec_sha256'])

    def test_missing_ocr_blocks_explicitly(self):
        from app.services.director import inspection_dependencies
        from unittest.mock import patch
        with patch('app.services.director.shutil.which', return_value=None):
            with self.assertRaisesRegex(vea.VeaError, 'Tesseract'):
                inspection_dependencies('en')

    def test_attempt_binding_cannot_be_rewritten_with_a_different_key(self):
        from app.services.director import ReceiptStore, Conflict
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            store = ReceiptStore(Path(folder) / 'jobs.sqlite3')
            store.submit('scene', payload())
            changed = payload(); changed['idempotency_key'] = 'another-key'
            changed['scene']['narration_chunk'] = 'Changed narration.'
            changed['spec_sha256'] = vea.content_hash(changed['scene'])
            with self.assertRaises(Conflict): store.submit('scene', changed)

    def test_api_requires_bearer_and_reconciles_persisted_submission(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.controllers.v1.director import router
        from app.services.director import ReceiptStore
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / 'storage') as folder:
            store = ReceiptStore(Path(folder) / 'jobs.sqlite3')
            app = FastAPI(); app.include_router(router)
            with patch.dict('os.environ', {'MPT_API_KEY': 'test-key'}), patch('app.services.director.store', return_value=store), patch('app.services.director.execute') as execute:
                client = TestClient(app)
                self.assertEqual(client.post('/api/v1/director/scenes', json=payload()).status_code, 401)
                headers = {'Authorization': 'Bearer test-key'}
                response = client.post('/api/v1/director/scenes', json=payload(), headers=headers)
                self.assertEqual(response.status_code, 202, response.text)
                receipt = response.json()
                self.assertEqual(store.get(receipt['task_id'], 'org')['status'], 'queued')
                self.assertEqual(client.get('/api/v1/director/tasks/'+receipt['task_id'], params={'org_id': 'other'}, headers=headers).status_code, 404)
                retry = client.post('/api/v1/director/scenes', json=payload(), headers=headers)
                self.assertEqual(receipt['task_id'], retry.json()['task_id'])
                self.assertTrue(execute.called)


if __name__ == '__main__': unittest.main()
