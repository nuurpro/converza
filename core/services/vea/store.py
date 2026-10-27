"""Transactional VEA variants backed by the existing Milo build queue.

The memory adapter and service-only SQL RPC use the same state transitions.
Paid render submission remains exclusively in Milo's leased worker.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import re
import unicodedata
import uuid

import httpx
from starlette.concurrency import run_in_threadpool
from services.milo.store import MiloStore, _id, _job, _now
from services.workflow.state import WorkflowConflict, apply_transition
from .contracts import PRESETS, VeaVideoArtifact


def enabled():
    return os.getenv('VEA_PRESETS_ENABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')


async def fetch_renderer(resource, params=None):
    """Authenticated read-only catalog proxy. No renderer paths reach clients."""
    from services.milo.video import _control_headers
    from lib.moneyprinter import _base_url
    if resource not in ('assets', 'presets'):
        raise ValueError('Unsupported renderer catalog')
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f'{_base_url()}/api/v1/vea/{resource}', params=params, headers=_control_headers())
        response.raise_for_status()
        data = response.json().get('data')
        if not isinstance(data, dict) or not isinstance(data.get(resource), list):
            raise ValueError('Renderer returned an invalid catalog')
        return data


def _state(repo):
    if not hasattr(repo, '_vea_state'):
        repo._vea_state = {'variants': {}, 'decisions': {}, 'history': {}}
    return repo._vea_state


def _public(row):
    if row is None:
        return None
    out = deepcopy(row)
    manifest = out.pop('composition_manifest', None) or {}
    out.pop('brand_snapshot', None)
    out.pop('clip_overrides', None)
    out['segments'] = [{k: s[k] for k in ('segment_id', 'asset_id', 'start_ms', 'end_ms', 'scene_index') if k in s}
                       for s in manifest.get('segments', [])]
    return out


def _config(row, campaign, passport, reuse=None):
    palette=passport.get('hex_colors')
    palette=[v for v in palette if isinstance(v,str) and re.fullmatch(r'#[a-fA-F0-9]{6}',v)][:12] if isinstance(palette,list) else []
    return dict(schema_version=1,variant_id=row['id'], variant_revision=row['revision'], preset_id=row['preset_id'],
                preset_version=(reuse or {}).get('preset',{}).get('version'),preset_sha256=(reuse or {}).get('preset_sha256'),
                brand_snapshot={'revision':campaign['artifact']['brand_revision'],'hex_colors':palette}, product_id=campaign.get('product_id'),
                clip_overrides=[{'segment_id':k,'asset_id':v} for k,v in sorted((row.get('clip_overrides') or {}).items())], reuse_manifest=deepcopy(reuse))


def _relevant_replacement(asset, segment, campaign, language):
    # Mirror the renderer's positive lexical-match gate, not its BM25 ranking.
    def token(value):
        value = unicodedata.normalize('NFKC', value).casefold()
        for apostrophe in '\u2018\u2019\u02bb\u02bc`\u00b4':
            value = value.replace(apostrophe, "'")
        return ''.join(c for c in value if c.isalnum() or c == "'")

    index = segment.get('scene_index')
    scenes = campaign['artifact']['video_script']
    if type(index) is not int or not 0 <= index < len(scenes):
        return False
    tags = asset.get('tags') or {}
    query = {token(t) for t in scenes[index]['visual_broll_cues'].split()} - {''}
    values = tags.get(language, []) + tags.get('und', [])
    return bool(query & {token(t) for value in values for t in value.split()})


class VeaStore:
    def __init__(self, repo):
        self.repo = repo
        self.milo = MiloStore(repo)
        self.memory = self.milo.memory
        if self.memory:
            self.state = _state(repo)

    async def _rpc(self, action, **args):
        try:
            return (await run_in_threadpool(self.repo.client.rpc('vea_store', {'p_action': action, 'p_args': args}).execute)).data
        except Exception as exc:
            if 'workflow_conflict' in str(exc) or 'workflow_not_found' in str(exc) or 'invalid input syntax for type uuid' in str(exc):
                raise WorkflowConflict('VEA organization, revision, evidence, or lease conflict') from exc
            raise

    def _campaign(self, org, campaign_id, expected_revision=None):
        c = self.milo.state['campaigns'].get(campaign_id)
        if not c or c['org_id'] != org or c['script_status'] != 'approved' or (expected_revision is not None and c['revision'] != expected_revision):
            raise WorkflowConflict('An approved current Milo script is required')
        self.milo._check_evidence(org, c['artifact'])
        return c

    def _row(self, org, id, revision=None):
        row = self.state['variants'].get(id)
        if not row or row['org_id'] != org or (revision is not None and row['revision'] != revision):
            raise WorkflowConflict('VEA variant revision or organization conflict')
        return row

    def _replay(self, org, key, request):
        if not key or len(key) > 200:
            raise ValueError('An idempotency key of at most 200 characters is required')
        prior = self.state['decisions'].get((org, key))
        if prior:
            if prior[0] != request:
                raise WorkflowConflict('Idempotency key reused with a different request')
            return deepcopy(prior[1])

    def _receipt(self, org, key, request, row):
        result = _public(row)
        self.state['decisions'][(org, key)] = deepcopy(request), result
        return deepcopy(result)

    def _new(self, c, preset, default=False):
        row = dict(id=_id(), org_id=c['org_id'], campaign_id=c['id'], approved_script_revision=c['revision']-1,
                   product_id=c.get('product_id'),language=c['artifact'].get('language') or c.get('language') or 'en',
                   revision=1, preset_id=preset, status='queued', job_id=None, draft_id=None, artifact=None,
                   error=None, is_default=default, composition_manifest=None, clip_overrides={},
                   brand_snapshot=deepcopy(self.repo.brand_passports.get(c['org_id'], {})), created_at=_now(), updated_at=_now())
        self.state['variants'][row['id']] = row
        return row

    def _enqueue(self, row, campaign, reuse=None):
        cfg = _config(row, campaign, row['brand_snapshot'], reuse)
        payload = dict(campaign_id=campaign['id'], script_revision=row['approved_script_revision'],
                       video_script=deepcopy(campaign['artifact']['video_script']),
                       language=campaign['artifact'].get('language') or campaign.get('language') or 'en',
                       submission_state='not_submitted', provider_attempt=1, variant_id=row['id'],
                       variant_revision=row['revision'], vea_config=cfg)
        job = _job(self.milo.state, row['org_id'], 'build', payload, f'vea:{row["id"]}:{row["revision"]}', campaign['id'])
        row.update(job_id=job['id'], status='queued', error=None, updated_at=_now())
        if row['is_default']:
            campaign.update(build_status='queued', result=None, updated_at=_now())
        return job

    async def list_variants(self, org):
        if not self.memory:
            return [_public(r) for r in await self._rpc('list', org=org)]
        return [_public(r) for r in sorted(self.state['variants'].values(), key=lambda r:r['created_at'], reverse=True) if r['org_id']==org]

    async def get_variant(self, org, id):
        if not self.memory:
            try: uuid.UUID(id)
            except (TypeError,ValueError): return None
            return _public(await self._rpc('get', org=org, id=id))
        row = self.state['variants'].get(id)
        return _public(row) if row and row['org_id']==org else None

    async def create_variant(self, org, campaign_id, expected_revision, preset_id, key):
        if preset_id not in PRESETS:
            raise ValueError('Unknown VEA preset')
        if not self.memory:
            return _public(await self._rpc('create', org=org, campaign_id=campaign_id, revision=expected_revision, preset_id=preset_id, key=key))
        async with self.repo._lock:
            req = ['create', campaign_id, expected_revision, preset_id]
            prior = self._replay(org, key, req)
            if prior is not None: return prior
            c = self._campaign(org, campaign_id, expected_revision)
            row = self._new(c, preset_id)
            self._enqueue(row, c)
            return self._receipt(org, key, req, row)

    async def prepare(self, job):
        if not self.memory:
            return await self._rpc('prepare', job=job['id'], token=job['lease_token'])
        async with self.repo._lock:
            j = self.milo._leased(job)
            if j['kind'] != 'build': raise WorkflowConflict('Wrong job kind')
            if j['payload'].get('variant_id'):
                row = self._row(j['org_id'], j['payload']['variant_id'], j['payload']['variant_revision'])
                if row['job_id'] != j['id']: raise WorkflowConflict('Variant build superseded')
                # A known provider receipt may finish even after evidence changes;
                # approval still revalidates current evidence.
                if j['payload'].get('submission_state') == 'not_submitted':
                    self._campaign(j['org_id'], j['campaign_id'], row['approved_script_revision']+1)
                row.update(status='rendering', updated_at=_now())
                return deepcopy(j)
            c = self._campaign(j['org_id'], j['campaign_id'])
            if c['revision']-1 != j['payload'].get('script_revision'):
                raise WorkflowConflict('Approved script revision changed')
            row = next((v for v in self.state['variants'].values() if v['job_id']==j['id']), None)
            if row is None:
                row = self._new(c, 'high_velocity_d2c', default=True)
            row.update(job_id=j['id'], status='rendering', updated_at=_now())
            j['payload'].update(variant_id=row['id'], variant_revision=row['revision'], vea_config=_config(row,c,row['brand_snapshot']))
            return deepcopy(j)

    async def complete(self, job, result):
        artifact, manifest = validate_artifact(job, result)
        if not self.memory:
            return await self._rpc('complete', job=job['id'], token=job['lease_token'], artifact=artifact, composition_manifest=manifest)
        async with self.repo._lock:
            j = self.milo._leased(job)
            row = self._row(j['org_id'], j['payload']['variant_id'], j['payload']['variant_revision'])
            if row['job_id'] != j['id']: raise WorkflowConflict('Variant build superseded')
            d = await self.repo.create_draft(j['org_id'], 'vea', 'Milo approved video variant', json.dumps(artifact, ensure_ascii=False))
            draft = next(draft for draft in self.repo.drafts if draft['id']==d['id'])
            draft.update(apply_transition(draft, 'ready', edited_content=json.dumps(artifact, ensure_ascii=False)))
            draft['vea_artifact'] = deepcopy(artifact)
            self.repo._event(j['org_id'], 'draft_transition', draft)
            row.update(status='completed', artifact=deepcopy(artifact), composition_manifest=deepcopy(manifest), draft_id=draft['id'], error=None, updated_at=_now())
            c = self.milo.state['campaigns'][j['campaign_id']]
            if row['is_default']:
                c.update(build_status='completed', result={**deepcopy(artifact),'draft_id':draft['id']}, updated_at=_now())
            self.milo._done(j)
            return deepcopy(c)

    async def swap(self, org, id, expected_revision, segment_id, asset_id, key):
        req = ['swap', id, expected_revision, segment_id, asset_id]
        if self.memory:
            async with self.repo._lock:
                prior = self._replay(org,key,req)
                if prior is not None: return prior
                row = self._row(org,id,expected_revision)
                c = self._campaign(org,row['campaign_id'],row['approved_script_revision']+1)
                product_id, language = c.get('product_id'), c['artifact'].get('language') or c.get('language') or 'en'
                row, c = deepcopy(row), deepcopy(c)
        else:
            prior = await self._rpc('replay',org=org,key=key,request=req)
            if prior is not None: return _public(prior)
            row = await self._rpc('get',org=org,id=id)
            if not row: raise WorkflowConflict('Variant not found')
            c = await self.milo.get_campaign(org,row['campaign_id'])
            product_id, language = c.get('product_id'), c['artifact'].get('language') or c.get('language') or 'en'
        segment=next((s for s in (row.get('composition_manifest') or {}).get('segments',[]) if s.get('segment_id')==segment_id),None)
        if row['status']!='completed' or segment is None:
            raise WorkflowConflict('Only a completed timeline segment can be replaced')
        catalog = await fetch_renderer('assets', {'org_id':org,'product_id':product_id,'language':language})
        replacement=next((a for a in catalog['assets'] if a.get('id',a.get('asset_id'))==asset_id),None)
        if (replacement is None or replacement.get('kind')!='video' or
            replacement.get('duration_sec',0)*1000 < segment['end_ms']-segment['start_ms'] or
            not _relevant_replacement(replacement, segment, c, language)):
            raise WorkflowConflict('Replacement clip is not currently eligible')
        if not self.memory:
            return _public(await self._rpc('swap',org=org,id=id,revision=expected_revision,segment_id=segment_id,asset_id=asset_id,key=key,request=req))
        async with self.repo._lock:
            prior = self._replay(org,key,req)
            if prior is not None: return prior
            row = self._row(org,id,expected_revision)
            c = self._campaign(org,row['campaign_id'],row['approved_script_revision']+1)
            manifest = row.get('composition_manifest') or {}
            if row['status']!='completed' or not any(s.get('segment_id')==segment_id for s in manifest.get('segments',[])):
                raise WorkflowConflict('Only a completed timeline segment can be replaced')
            self.state['history'][(id,row['revision'])] = deepcopy(row)
            old_draft = next((d for d in self.repo.drafts if d['id']==row['draft_id']), None)
            if old_draft and old_draft['status']=='AWAITING_HITL':
                old_draft.update(apply_transition(old_draft,'reject'))
                old_draft['vea_artifact']['superseded'] = True
                self.repo._event(org,'draft_transition',old_draft)
            elif old_draft:
                old_draft['vea_artifact']['superseded'] = True
                old_draft.update(status='REJECTED',final_content=None,decided_at=_now(),revision=old_draft['revision']+1,updated_at=_now())
                self.repo._event(org,'draft_transition',old_draft)
            row.update(revision=row['revision']+1, artifact=None, draft_id=None)
            row['clip_overrides'][segment_id] = asset_id
            self._enqueue(row,c,reuse=manifest)
            return self._receipt(org,key,req,row)

    async def retry(self, org, id, expected_revision, key):
        if not self.memory:
            return _public(await self._rpc('retry',org=org,id=id,revision=expected_revision,key=key))
        # MiloStore owns submission uncertainty protections. Its helper works
        # under this lock, avoiding nested acquisition and race windows.
        async with self.repo._lock:
            req = ['retry',id,expected_revision]
            prior = self._replay(org,key,req)
            if prior is not None: return prior
            row = self._row(org,id,expected_revision)
            self._campaign(org,row['campaign_id'],row['approved_script_revision']+1)
            if row['status']!='failed': raise WorkflowConflict('Only failed variants can be retried')
            j = self.milo.state['jobs'][row['job_id']]
            self.milo._retry_locked(org,j['id'])
            row.update(status='queued',error=None,updated_at=_now())
            return self._receipt(org,key,req,row)


def validate_artifact(job, result):
    payload = job['payload']
    raw = result.get('vea_artifact') or result.get('artifact',result)
    manifest = result.get('composition_manifest') or raw.get('composition_manifest') or {}
    artifact = VeaVideoArtifact.model_validate({k:v for k,v in raw.items() if k in VeaVideoArtifact.model_fields}).model_dump(mode='json')
    if (artifact['id'],artifact['variant_revision'],artifact['source_milo_script_id'],artifact['approved_script_revision'],artifact['preset_used']) != (
        payload['variant_id'],payload['variant_revision'],job['campaign_id'],payload['script_revision'],payload['vea_config']['preset_id']):
        raise WorkflowConflict('Renderer artifact does not match the approved variant')
    if not isinstance(manifest,dict) or not isinstance(manifest.get('segments'),list) or not manifest['segments']:
        raise ValueError('Composition manifest must contain rendered timeline segments')
    from services.milo.video import build_binding
    binding=build_binding(job)
    digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    if (artifact['composition_sha256']!=digest or manifest.get('org_id')!=job['org_id'] or
        manifest.get('script_sha256')!=binding['script_sha256'] or manifest.get('vea_config_sha256')!=binding['vea_config_sha256']):
        raise WorkflowConflict('Composition manifest hash or approved input binding is invalid')
    config=payload['vea_config']
    if ((config.get('preset_version') is not None and config['preset_version']!=artifact['preset_version']) or
        (config.get('preset_sha256') is not None and config['preset_sha256']!=artifact['preset_sha256'])):
        raise WorkflowConflict('Rendered preset does not match the pinned recipe')
    preset=manifest.get('preset')
    if not isinstance(preset,dict):
        raise WorkflowConflict('Composition manifest is missing its recipe snapshot')
    preset_digest=hashlib.sha256(json.dumps(preset,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    if (manifest.get('preset_sha256')!=preset_digest or preset_digest!=artifact['preset_sha256']
        or preset.get('id')!=artifact['preset_used'] or preset.get('version')!=artifact['preset_version']):
        raise WorkflowConflict('Composition recipe snapshot differs from the rendered artifact')
    duration_ms=manifest.get('duration_ms')
    if type(duration_ms) is not int or duration_ms<=0 or abs(artifact['duration_sec']-duration_ms/1000)>1/30+.001:
        raise WorkflowConflict('Rendered duration differs from the composition timeline')
    return artifact,manifest


async def prepare_build(job, store):
    payload = job['payload']
    if not payload.get('variant_id') and (payload.get('provider_task_id') or payload.get('task_id') or payload.get('submission_state') not in (None,'not_submitted')):
        return job
    return await VeaStore(store.repo).prepare(job)


async def validate_review(repo, draft):
    artifact = draft.get('vea_artifact')
    if not artifact: return
    store = VeaStore(repo)
    org = draft['org_id']
    if store.memory:
        async with repo._lock:
            row = store._row(org,artifact['id'],artifact['variant_revision'])
            if row['draft_id']!=draft['id'] or row['status']!='completed': raise WorkflowConflict('Video revision superseded')
            c = deepcopy(store._campaign(org,row['campaign_id'],row['approved_script_revision']+1))
            manifest = deepcopy(row['composition_manifest'])
    else:
        data = await store._rpc('validate_review',org=org,id=artifact['id'],revision=artifact['variant_revision'],draft_id=draft['id'])
        c,manifest = data['campaign'],data['composition_manifest']
    catalog = await fetch_renderer('assets',{'org_id':org,'product_id':c.get('product_id'),'language':c['artifact'].get('language') or c.get('language') or 'en'})
    eligible = {a.get('id',a.get('asset_id')):a for a in catalog['assets']}
    references=list(manifest.get('segments',[]))
    if manifest.get('music'):references.append(manifest['music'])
    for segment in references:
        asset = eligible.get(segment.get('asset_id'))
        if asset is None or (segment.get('asset_sha256') and asset.get('sha256') != segment['asset_sha256']):
            raise WorkflowConflict('Rendered clip is no longer eligible; replace it and render again')
