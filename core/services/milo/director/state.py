"""Deterministic director DAG transitions, shared by memory and SQL adapters.

The durable aggregate is written using a fenced version compare-and-swap. Every
attempt is immutable once finished; retries append nodes, never rewind them.
"""
from copy import deepcopy
import hashlib
import json
import re
import time
import uuid

from services.workflow.state import WorkflowConflict


def uid():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def event(run, state, message, task=None):
    run['state'] = state
    run.setdefault('progress', []).append(dict(id=uid(), state=state, message=message,
        run_id=run['id'], storyboard_revision=run['storyboard_revision'],
        scene_index=task.get('scene_index') if task else run.get('scene_index'),
        scene_count=len(run['scenes']), attempt=task.get('attempt', 0) if task else 0))


def append_task(run, kind, scene=None, previous=None, correction=None):
    index = scene['scene_index'] if scene else None
    if scene:
        specification = deepcopy(scene['specification'])
    else:
        specification = dict(schema_version=1, storyboard_revision=run['storyboard_revision'],
            scenes=[dict(scene_index=s['scene_index'], task_id=s['verified']['task_id'],
                artifact_sha256=s['verified']['artifact_sha256'], verified_token=s['verified']['token'])
                for s in run['scenes']],
            target_duration_sec=sum(s['specification'].get('target_duration_sec',
                s['specification'].get('target_duration_seconds', 0)) for s in run['scenes'])
                -0.15*run.get('transitions',[]).count('crossfade'),
            transitions=run.get('transitions', []), width=1080, height=1920, format='mp4', audio_ducking_db=-18)
        if run.get('background_asset_id'):
            specification['background_asset_id']=run['background_asset_id']
    task = dict(id=uid(), org_id=run['org_id'], campaign_id=run['campaign_id'],
        run_id=run['id'], approved_revision=run['approved_revision'],
        product_id=run.get('product_id'),
        reuse_context_hash=run.get('reuse_context_hash'),
        storyboard_revision=run['storyboard_revision'], language=run.get('language', 'en'),
        kind=kind, scene_index=index, attempt=previous['attempt']+1 if previous else 1,
        parent_attempt_id=previous['id'] if previous else None, specification=specification,
        spec_hash=digest(specification), status='pending', lease_token=None, lease_until=0,
        receipt=None, submission_uncertain=False, correction=correction, result=None, verification=None)
    task['narration_chunks'] = [s['specification'].get('narration_chunk',s['specification'].get('narration',''))
                                for s in run['scenes']]
    task['renderer_context']=deepcopy((run.get('reuse_context') or {}).get('renderer'))
    task['scene_prompts']=[deepcopy(s['specification']) for s in run['scenes']]
    task['idempotency_key'] = 'milo-director:' + task['id']
    run['tasks'].append(task)
    if scene:
        scene['state'] = 'DIRECTING_SCENE'
        run['scene_index'] = index
    event(run, 'DIRECTING_SCENE' if scene else 'ASSEMBLING_MASTER',
          f"Rendering scene {index}" if scene else 'Assembling verified scenes', task)
    return task


def advance(run):
    if not run['script_approved']:
        event(run, 'AWAITING_SCRIPT_APPROVAL', 'Narration requires approval')
        return
    for scene in run['scenes']:
        if scene.get('verified'):
            if scene['state'] != 'SCENE_VERIFIED':
                scene['state'] = 'SCENE_VERIFIED'
                run['scene_index'] = scene['scene_index']
                event(run, 'SCENE_VERIFIED', 'Reusing unchanged verified scene')
            continue
        append_task(run, 'scene', scene)
        return
    append_task(run, 'master')


def new_run(org, campaign_id, approved_revision, scenes, key, *, script_approved=True,
            parent=None, storyboard_revision=None, language='en', transitions=None,reuse_context=None,
            background_asset_id=None,product_id=None):
    if not 1 <= len(scenes) <= 12:
        raise ValueError('Storyboard requires 1 to 12 ordered scenes')
    if [s.get('scene_index') for s in scenes] != list(range(1, len(scenes)+1)):
        raise ValueError('Scene indices must be consecutive and 1-based')
    if transitions and (len(transitions)!=len(scenes)-1 or any(t not in ('cut','crossfade') for t in transitions)):
        raise ValueError('Transitions must describe every scene boundary')
    if background_asset_id is not None and (not isinstance(background_asset_id,str) or not background_asset_id.strip()):
        raise ValueError('Background audio requires an asset identifier')
    run = dict(id=uid(), org_id=org, campaign_id=campaign_id, approved_revision=approved_revision,
        storyboard_revision=storyboard_revision or (parent['storyboard_revision']+1 if parent else 1),
        key=key, script_approved=script_approved, language=language, transitions=transitions or [],
        background_asset_id=background_asset_id,
        product_id=product_id,
        parent_run_id=parent['id'] if parent else None, superseded_by=None,
        state='DIRECTING_SCENE', version=0, scenes=[], tasks=[], progress=[], draft_id=None,
        created_at=time.time())
    run['reuse_context']=deepcopy(reuse_context)
    run['reuse_context_hash']=digest({'source':run['reuse_context'],'language':language,'product_id':product_id}) if reuse_context is not None else None
    for spec in scenes:
        scene = dict(scene_index=spec['scene_index'], specification=deepcopy(spec),
                     spec_hash=digest(spec), state='PENDING', verified=None)
        if parent and run['reuse_context_hash'] is not None and parent.get('reuse_context_hash')==run['reuse_context_hash']:
            cached = next((s for s in parent['scenes'] if s['spec_hash']==scene['spec_hash'] and s.get('verified')), None)
            if cached:
                scene['verified'] = deepcopy(cached['verified'])
        run['scenes'].append(scene)
    advance(run)
    return run


def fenced(run, supplied):
    if run.get('superseded_by') or run.get('document_fenced'):
        raise WorkflowConflict('Superseded director run')
    task = next((t for t in run['tasks'] if t['id'] == supplied['id']), None)
    if not task or task['org_id'] != supplied.get('org_id') or task['run_id'] != supplied.get('run_id'):
        raise WorkflowConflict('Unknown director task')
    if task['status'] == 'completed':
        return task
    if task['lease_token'] != supplied.get('lease_token') or task['lease_until'] <= time.time():
        raise WorkflowConflict('Director lease expired or fenced')
    return task


def fail_task(run, task, error, correction=None):
    task['status'] = 'failed'
    task['last_error'] = str(error)
    task['lease_until'] = 0
    if task['attempt'] >= 3:
        event(run, 'BLOCKED', f"{task['kind']} exhausted three attempts: {error}", task)
        run['alert'] = dict(error=str(error), task_id=task['id'], correction=correction)
        return
    scene = next((s for s in run['scenes'] if s['scene_index']==task['scene_index']), None)
    append_task(run, task['kind'], scene, task, correction or {'violations': [str(error)]})


def complete_task(run, task, result, verification):
    if task['status'] == 'completed':
        return
    if not task.get('receipt') or not task['receipt'].get('task_id'):
        raise WorkflowConflict('Inspection requires a persisted renderer receipt')
    task['result'] = deepcopy(result)
    task['verification'] = deepcopy(verification)
    if verification.get('passed') is not True:
        fail_task(run, task, '; '.join(verification.get('violations', [])) or 'Inspection failed', verification)
        return
    artifact_hash = result.get('artifact_sha256') or result.get('artifact_hash')
    if not isinstance(artifact_hash, str) or not re.fullmatch(r'[a-f0-9]{64}',artifact_hash):
        raise WorkflowConflict('Verified artifact requires immutable SHA256')
    for key,expected in [('spec_sha256',task['spec_hash']),('scene_index',task['scene_index']),
                         ('attempt',task['attempt']),('artifact_sha256',artifact_hash)]:
        if key in verification and verification[key] != expected:
            raise WorkflowConflict('Inspection evidence belongs to a different attempt or artifact')
    task['status'] = 'completed'
    task['lease_until'] = 0
    if task['kind'] == 'scene':
        scene = next(s for s in run['scenes'] if s['scene_index']==task['scene_index'])
        scene['verified'] = dict(token=uid(), task_id=task['receipt']['task_id'],
            source_attempt_id=task['id'], artifact_sha256=artifact_hash,
            spec_hash=task['spec_hash'], result=deepcopy(result), verification=deepcopy(verification),
            reuse_context_hash=run.get('reuse_context_hash'),
            org_id=run['org_id'], campaign_id=run['campaign_id'], approved_revision=run['approved_revision'])
        scene['state'] = 'SCENE_VERIFIED'
        event(run, 'SCENE_VERIFIED', f"Scene {task['scene_index']} automated checks passed", task)
        advance(run)
    else:
        run['draft_id'] = run['draft_id'] or uid()
        run['master_result'] = deepcopy(result)
        run['inspection_report'] = deepcopy(verification)
        event(run, 'AWAITING_HITL', 'Milo recommends approval · automated checks passed', task)
