"""Exercise actual local scene -> inspection -> master APIs without downloads.

Fixtures JSON: [{audio_path, approved_text, overlay_text, language}]. Audio paths
resolve beside the JSON file. Use independently annotated human recordings for
speech accuracy claims; this integration report proves media plumbing only.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

PROVIDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROVIDER))
sys.path.insert(0, str(PROVIDER.parents[2] / 'core'))
from app.services import director, vea
from app.controllers.v1.director import router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.milo.director.contracts import ScenePromptPayload, MasterAssemblyManifest
from services.milo.director.verification import verify_scene, verify_master


async def durable_worker_pipeline(app, specs, context, transitions, background_asset_id):
    """Real HTTP provider, durable state machine; coherence alone is a test double."""
    import httpx
    from lib.repository import InMemoryRepository
    from services.milo.director.documents import DirectorDocuments
    from services.milo.director.store import DirectorStore
    from services.milo.director.worker import DirectorWorker
    from services.milo.director.provider import DirectorProvider
    repo = InMemoryRepository()
    org, campaign = 'local-director-test', 'durable-local-campaign'
    repo._milo_state = {'campaigns': {campaign: {'id': campaign, 'org_id': org, 'revision': 1, 'product_id': None, 'script_status': 'approved'}}}
    docs = DirectorDocuments(repo)
    await docs.command(org, campaign, 'initialize', board={'revision': 1, 'scenes': specs, 'narration_approved': True}, campaign_revision=1, key='approved-fixture')
    store = DirectorStore(repo)
    run = await store.create_run(org, campaign, 1, specs, 'local-complete-render', storyboard_revision=1,
                                 language='en', reuse_context={'renderer': context}, transitions=transitions, background_asset_id=background_asset_id)
    dispatched = []
    class RecordingProvider(DirectorProvider):
        async def submit(self, task):
            current = await store.get(org, run['id'])
            if task['kind'] == 'scene':
                assert all(s.get('verified') for s in current['scenes'][:task['scene_index']-1]), 'Successor rendered before predecessor verification'
            else:
                assert all(s.get('verified') for s in current['scenes']), 'Master assembled before all scenes verified'
            dispatched.append({'kind': task['kind'], 'scene_index': task['scene_index'], 'attempt': task['attempt']})
            return await super().submit(task)
    async def model_stub(*_args, **_kwargs): return {'passed': True, 'reasons': []}
    async def master_verifier(task, result): return await verify_master(task, result, model=model_stub)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        worker = DirectorWorker(repo, renderer=RecordingProvider(client), scene_verifier=verify_scene, master_verifier=master_verifier)
        for _ in range(12):
            await worker.run_once()
            current = await store.get(org, run['id'])
            if current['state'] in ('AWAITING_HITL', 'BLOCKED'): break
        assert current['state'] == 'AWAITING_HITL', json.dumps(current, ensure_ascii=False)
        assert len(repo.drafts) == 1 and repo.drafts[0]['status'] == 'AWAITING_HITL'
        assert await worker.run_once() == 0
        assert len(repo.drafts) == 1
        assert [d['scene_index'] for d in dispatched if d['kind']=='scene'] == list(range(1, len(specs)+1))
        assert not any('AWAITING_SCENE_VISUAL_APPROVAL' in e['state'] for e in current['progress'])
    return {'passed': True, 'run': current, 'draft': repo.drafts[0], 'dispatch_order': dispatched,
            'event_count': len(repo.events), 'durability_scope': 'in-memory core repository; durable SQLite provider receipts; PostgreSQL concurrency verified separately',
            'coherence_model_test_double': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('fixtures', type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--tesseract', required=True, type=Path)
    parser.add_argument('--crossfade', action='store_true')
    parser.add_argument('--music', action='store_true')
    parser.add_argument('--durable-worker', action='store_true')
    args = parser.parse_args()
    work = args.workspace.resolve(); work.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads(args.fixtures.read_text(encoding='utf-8'))
    assets = work / 'assets'; assets.mkdir(exist_ok=True)
    recordings = work / 'recordings'; recordings.mkdir(exist_ok=True)
    os.environ.update(VEA_WHISPER_MODEL=str(args.model.resolve()), VEA_TESSERACT=str(args.tesseract.resolve()),
                      VEA_DIRECTOR_ROOT=str(work / 'artifacts'), VEA_DIRECTOR_DB=str(work / 'jobs.sqlite3'),
                      VEA_ASSET_ROOT=str(assets), VEA_DIRECTOR_NARRATION_ROOT=str(recordings), MPT_API_KEY='local-director-validation-only')
    clip = assets / 'source.mp4'
    vea.run_media(['-f', 'lavfi', '-i', 'color=c=0x20304f:s=1080x1920:r=30:d=10', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-pix_fmt', 'yuv420p', clip])
    catalog = [{'id': 'local-fit-footage', 'org_id': 'local-director-test', 'path': 'source.mp4', 'sha256': vea.file_hash(clip),
                'kind': 'video', 'rights_confirmed': True, 'permitted_uses': ['advertising'], 'product_ids': [],
                'width': 1080, 'height': 1920, 'duration_sec': 10, 'tags': {'en': ['fit', 'sku-local'], 'ru': ['fit', 'sku-local'], 'uz': ['fit', 'sku-local']}}]
    if args.music:
        music = assets / 'music.wav'
        vea.run_media(['-f', 'lavfi', '-i', 'sine=frequency=220:duration=10', '-ar', '48000', '-ac', '2', music])
        catalog.append({'id': 'local-music', 'org_id': 'local-director-test', 'path': 'music.wav', 'sha256': vea.file_hash(music), 'kind': 'music',
                        'rights_confirmed': True, 'permitted_uses': ['advertising'], 'product_ids': [], 'duration_sec': 10, 'tags': {}})
    vea.atomic_json(assets / 'catalog.json', {'schema_version': 1, 'assets': catalog})
    recording_catalog = []
    for index, fixture in enumerate(fixtures):
        source = (args.fixtures.resolve().parent / fixture['audio_path']).resolve()
        target = recordings / f'scene-{index+1}.wav'; shutil.copyfile(source, target)
        recording_catalog.append({'org_id': 'local-director-test', 'language': fixture['language'], 'text_sha256': vea.content_hash(fixture['approved_text']),
                                  'path': target.name, 'audio_sha256': vea.file_hash(target)})
    vea.atomic_json(recordings / 'catalog.json', {'recordings': recording_catalog})
    app = FastAPI(); app.include_router(router)
    client = TestClient(app, headers={'Authorization': 'Bearer local-director-validation-only'})
    context = client.get('/api/v1/director/context', params={'org_id': 'local-director-test', 'language': fixtures[0]['language']})
    context.raise_for_status()
    scene_tokens, reports, total, narration, specs = [], [], 0, [], []
    for index, fixture in enumerate(fixtures):
        duration = round(vea.media_duration(recordings / f'scene-{index+1}.wav') + .5, 1)
        spec = ScenePromptPayload(scene_index=index+1, total_scenes=len(fixtures), target_duration_sec=duration,
            narration_chunk=fixture['approved_text'], visual_directive={'prompt': 'fit', 'subject_action': 'display', 'camera_movement': 'static', 'lighting_style': 'soft'},
            asset_constraints={'required_sku_tags': ['sku-local'], 'brand_hex_palette': ['#FFFFFF'], 'negative_visual_constraints': []},
            overlay_text={'text': fixture['overlay_text'], 'font_family': 'Arial', 'font_size': 64, 'color': '#FFFFFF', 'position': 'center',
                          'animation': fixture.get('animation', 'none'), 'start_sec': 0, 'end_sec': duration}).model_dump(mode='json')
        binding = {'org_id': 'local-director-test', 'run_id': 'local-run', 'campaign_id': 'local-campaign', 'storyboard_revision': 1,
                   'attempt': 1, 'spec_sha256': vea.content_hash(spec), 'idempotency_key': f'scene-{index+1}', 'expected_context': context.json()}
        response = client.post('/api/v1/director/scenes', json={**binding, 'scene': spec, 'language': fixture['language']})
        response.raise_for_status(); task_id = response.json()['task_id']
        receipt = client.get('/api/v1/director/tasks/'+task_id, params={'org_id': binding['org_id']}).json()
        if receipt['status'] != 'complete':
            print(json.dumps(receipt, ensure_ascii=False, indent=2)); return 1
        task = {**binding, 'specification': spec, 'spec_hash': binding['spec_sha256'], 'scene_index': index+1, 'renderer_context': context.json()}
        specs.append(spec)
        verdict = asyncio.run(verify_scene(task, receipt['result']))
        reports.append({'task_id': task_id, 'verdict': verdict, 'result': receipt['result']})
        if not verdict['passed']:
            vea.atomic_json(work / 'report.json', {'passed': False, 'scene_reports': reports})
            print(json.dumps(verdict, indent=2)); return 1
        scene_tokens.append({'scene_index': index+1, 'task_id': task_id, 'artifact_sha256': receipt['result']['artifact_sha256'],
                             'verified_token': vea.content_hash(verdict)})
        total += duration; narration.append(fixture['approved_text'])
    transitions = ['crossfade' if args.crossfade else 'cut'] * (len(fixtures)-1)
    total -= transitions.count('crossfade') * .15
    manifest = MasterAssemblyManifest(storyboard_revision=1, scenes=scene_tokens, target_duration_sec=total, transitions=transitions,
                                      **({'background_asset_id': 'local-music'} if args.music else {})).model_dump(mode='json')
    binding.update(spec_sha256=vea.content_hash(manifest), idempotency_key='master')
    response = client.post('/api/v1/director/masters', json={**binding, 'manifest': manifest})
    response.raise_for_status(); task_id = response.json()['task_id']
    receipt = client.get('/api/v1/director/tasks/'+task_id, params={'org_id': binding['org_id']}).json()
    if receipt['status'] != 'complete': print(json.dumps(receipt, ensure_ascii=False, indent=2)); return 1
    async def model_stub(*_args, **_kwargs): return {'passed': True, 'reasons': []}
    verdict = asyncio.run(verify_master({'specification': manifest, 'narration_chunks': narration, 'scene_prompts': specs,
                                        'org_id': binding['org_id'], 'renderer_context': context.json()}, receipt['result'], model=model_stub))
    report = {'passed': verdict['passed'], 'scope': 'actual local speech, Whisper, OCR and FFmpeg integration; coherence model is a test double; no human boundary accuracy claim',
              'context': context.json(), 'scene_reports': reports, 'master_report': verdict, 'master_result': receipt['result']}
    if args.durable_worker and verdict['passed']:
        report['durable_worker'] = asyncio.run(durable_worker_pipeline(app, specs, context.json(), transitions, 'local-music' if args.music else None))
    vea.atomic_json(work / 'report.json', report)
    print(json.dumps({'passed': verdict['passed'], 'report': str(work / 'report.json'), 'master': task_id, 'violations': verdict['violations']}, indent=2))
    return 0 if verdict['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
