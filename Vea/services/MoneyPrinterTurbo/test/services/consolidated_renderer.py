"""JSON-lines TestClient bridge for the isolated core journey, not a server entrypoint.

Only speech synthesis and acoustic timestamps are fixtures. The actual approved
renderer API, queue, SQLite receipts, matching, alignment, captions and FFmpeg run.
The candidate's running ASGI process and its storage are never modified.
"""
import base64
from contextlib import ExitStack, redirect_stdout
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from unittest.mock import patch
from uuid import UUID


def forbidden(*args, **kwargs):
    raise AssertionError('The journey must not contact a provider or generate unapproved copy')


def serve(config, output):
    root = Path(config['root'])
    if not re.fullmatch(r'/tmp/consolidated-journey-[a-f0-9]{32}', str(root)):
        raise ValueError('An isolated journey root is required')
    UUID(config['org_id']); UUID(config['product_id'])
    root.mkdir(exist_ok=False)
    assets = root / 'assets'
    assets.mkdir()
    os.environ.update(MPT_APPROVED_ONLY='1', MPT_API_KEY=config['key'],
        MPT_STATE_DB=str(root / 'receipts.sqlite3'), VEA_ENABLED='1',
        VEA_ASSET_ROOT=str(assets), VEA_PUBLIC_ENDPOINT='http://renderer.journey.invalid',
        VEA_X264_PRESET='ultrafast', ELEVENLABS_API_KEY='', VEA_PIPER_VOICES='{}')
    from app.services import vea
    from app.utils import utils

    def storage_dir(sub_dir='', create=False):
        path = root / 'storage' / sub_dir
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def task_dir(sub_dir=''):
        path = Path(storage_dir()) / 'tasks' / sub_dir
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    vea.run_media(['-f', 'lavfi', '-i', 'testsrc2=s=180x320:r=30:d=4',
                   '-c:v', 'libx264', '-pix_fmt', 'yuv420p', assets / 'fixture.mp4'])
    asset = {'id': 'journey-stitching', 'org_id': config['org_id'], 'product_ids': [config['product_id']],
        'path': 'fixture.mp4', 'sha256': vea.file_hash(assets / 'fixture.mp4'),
        'duration_sec': 4, 'width': 180, 'height': 320, 'kind': 'video',
        'rights_confirmed': True, 'permitted_uses': ['advertising'],
        'tags': {'en': ['Travel bag stitching product']}}
    (assets / 'catalog.json').write_text(json.dumps({'schema_version': 1, 'assets': [asset]}), encoding='utf-8')

    def speech(text, voice, language, cache_dir):
        if language != 'en':
            raise AssertionError('This fixture only provisions English')
        key = vea.content_hash({'fixture_text': text, 'language': language})
        target = Path(cache_dir) / (key + '.wav')
        duration = len(text.split()) * .22 + .12
        vea.run_media(['-f', 'lavfi', '-i', f'sine=frequency=440:duration={duration}',
                       '-ar', '48000', '-c:a', 'pcm_s16le', target])
        return {'path': str(target), 'cache_key': key, 'provider': 'journey-tone-fixture', 'fallback_used': False}

    def timestamps(audio, text, language, cache_dir):
        duration = round(vea.media_duration(audio) * 1000)
        observed = [{'word': token, 'start_ms': i * 220 + 10, 'end_ms': (i + 1) * 220}
                    for i, token in enumerate(text.split())]
        return vea.align_words(text, observed, duration)

    with ExitStack() as stack:
        stack.enter_context(patch.object(utils, 'storage_dir', storage_dir))
        stack.enter_context(patch.object(utils, 'task_dir', task_dir))
        stack.enter_context(patch.object(vea, 'synthesize_narration', speech))
        stack.enter_context(patch.object(vea, 'extract_word_timestamps', timestamps))
        stack.enter_context(patch.object(vea.request, 'urlopen', forbidden))
        import httpx
        stack.enter_context(patch.object(httpx.HTTPTransport, 'handle_request', forbidden))
        stack.enter_context(patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden))
        from app.asgi import app
        from app.config import config as app_config
        from app.services import state as sm
        from app.services import task as tm
        from app.services.sqlite_state import SQLiteState
        from fastapi.testclient import TestClient
        app_config.app['endpoint'] = 'http://renderer.journey.invalid'
        for name in ('generate_script', 'generate_terms'):
            if hasattr(tm, name):
                stack.enter_context(patch.object(tm, name, forbidden))
        client = stack.enter_context(TestClient(app, base_url='http://renderer.journey.invalid'))
        print(json.dumps({'ready': True, 'root': str(root), 'state_db': sm.state.filename}), file=output, flush=True)
        try:
            for line in sys.stdin:
                request = json.loads(line)
                if request['kind'] == 'close':
                    break
                if request['kind'] == 'http':
                    response = client.request(request['method'], request['path'],
                        headers=request.get('headers', {}), content=base64.b64decode(request.get('body', '')))
                    result = {'status': response.status_code, 'headers': dict(response.headers),
                              'body': base64.b64encode(response.content).decode('ascii')}
                elif request['kind'] == 'evidence':
                    task_id = str(UUID(request['task_id']))
                    receipt = SQLiteState(sm.state.filename).get_task(task_id)
                    if not receipt or receipt['state'] != 1:
                        raise AssertionError('A durable successful receipt is required')
                    folder = Path(task_dir(task_id))
                    video = folder / 'final-1.mp4'
                    thumbnail = folder / 'final-1.jpg'
                    probe = vea.probe_media(video)
                    stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
                    pixels = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-frames:v', '1',
                        '-vf', 'scale=16:16', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                        check=True, capture_output=True, timeout=30).stdout
                    result = {'width': stream['width'], 'height': stream['height'], 'codec': stream['codec_name'],
                        'audio_codecs': [s['codec_name'] for s in probe['streams'] if s['codec_type'] == 'audio'],
                        'duration_sec': float(probe['format']['duration']), 'pixel_range': max(pixels) - min(pixels),
                        'video_sha256': vea.file_hash(video), 'thumbnail_sha256': vea.file_hash(thumbnail),
                        'receipt': receipt, 'captions': (folder / 'captions.ass').read_text(encoding='utf-8'),
                        'manifest': json.loads((folder / 'composition.json').read_text(encoding='utf-8'))}
                else:
                    raise ValueError('Unsupported journey bridge command')
                print(json.dumps(result), file=output, flush=True)
        finally:
            sm.state.stop_runtime()


if __name__ == '__main__':
    protocol = sys.stdout
    initial = json.loads(sys.stdin.readline())
    with redirect_stdout(sys.stderr):
        serve(initial, protocol)
