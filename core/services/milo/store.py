"""Transactional Milo inbox, campaign review and leased build queue.

The in-memory adapter implements the same boundary as the service-only PostgreSQL
RPC. All customer text remains data; only exact, source-validated spans are stored.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from starlette.concurrency import run_in_threadpool
from services.workflow.state import WorkflowConflict
from .contracts import TOPICS


DEFAULTS = dict(daily_enabled=True, spike_enabled=True, daily_hour=9, timezone='Asia/Tashkent',
                spike_threshold=5, window_days=7, cooldown_hours=24)


def _id():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _state(repo):
    if not hasattr(repo, '_milo_state'):
        repo._milo_state = {k: {} for k in ('settings', 'campaigns', 'jobs', 'objections', 'decisions')}
    return repo._milo_state


def _job(state, org, kind, payload, key, campaign_id=None):
    previous = next((j for j in state['jobs'].values() if j['org_id'] == org and j['kind'] == kind and j['dedup_key'] == key), None)
    if previous:
        return previous
    row = dict(id=_id(), org_id=org, kind=kind, payload=deepcopy(payload), dedup_key=key,
               campaign_id=campaign_id, status='pending', attempts=0, available_at=0,
               lease_token=None, lease_until=None, last_error=None, created_at=_now())
    state['jobs'][row['id']] = row
    return row


def enqueue_inbound(repo, inbound):
    """Called under Sleyz's transaction lock; mirrors the database INSERT trigger."""
    env = inbound['envelope']
    external = str(env.get('external_message_id', ''))
    if env.get('simulated') or ':refresh' in external:
        return
    _job(_state(repo), inbound['org_id'], 'extract', dict(inbound_id=inbound['id'],
         prospect_id=inbound['prospect_id'], text=env['text'], received_at=inbound['received_at']), inbound['id'])


class MiloStore:
    def __init__(self, repo):
        self.repo = repo
        self.memory = not hasattr(repo, 'client')
        if self.memory:
            self.state = _state(repo)

    async def _rpc(self, operation, **args):
        try:
            return (await run_in_threadpool(self.repo.client.rpc('milo_store', {'p_action': operation, 'p_args': args}).execute)).data
        except Exception as exc:
            if 'workflow_conflict' in str(exc) or 'workflow_not_found' in str(exc):
                raise WorkflowConflict('Milo organization, revision, evidence, or lease conflict') from exc
            raise

    async def settings(self, org):
        if not self.memory:
            return await self._rpc('settings', org=org)
        return deepcopy({**DEFAULTS, **self.state['settings'].get(org, {})})

    async def save_settings(self, org, values):
        if set(values) - set(DEFAULTS):
            raise ValueError('Unknown Milo setting')
        current = {**await self.settings(org), **values}
        for name, low, high in [('daily_hour', 0, 23), ('spike_threshold', 1, 1000), ('window_days', 1, 365), ('cooldown_hours', 1, 720)]:
            if type(current[name]) is not int or not low <= current[name] <= high:
                raise ValueError(f'Invalid {name}')
        for name in ('daily_enabled', 'spike_enabled'):
            if type(current[name]) is not bool:
                raise ValueError(f'Invalid {name}')
        try:
            ZoneInfo(current['timezone'])
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            raise ValueError('Invalid timezone')
        if not self.memory:
            return await self._rpc('save_settings', org=org, values=values)
        async with self.repo._lock:
            self.state['settings'][org] = current
            return deepcopy(current)

    async def enqueue(self, org, trigger, prompt='', language=None, key='', topic=None, product_id=None, evidence_ids=None):
        if trigger not in ('manual', 'daily', 'spike'):
            raise ValueError('Invalid trigger')
        if not self.memory:
            return await self._rpc('enqueue', org=org, trigger=trigger, prompt=prompt, language=language, key=key, topic=topic, product_id=product_id, evidence_ids=evidence_ids)
        async with self.repo._lock:
            automatic = trigger != 'manual'
            existing = next((c for c in self.state['campaigns'].values() if c['org_id'] == org and c['dedup_key'] == key and (key or automatic)), None)
            if existing:
                if trigger == 'manual' and (existing['trigger'], existing['prompt'], existing['language']) != (trigger, prompt, language):
                    raise WorkflowConflict('Idempotency key reused with a different request')
                return deepcopy(existing)
            settings = {**DEFAULTS, **self.state['settings'].get(org, {})}
            if automatic and not settings[trigger + '_enabled']:
                return None
            if automatic and evidence_ids is not None:
                previous = sorted((c for c in self.state['campaigns'].values() if c['org_id'] == org and c['trigger'] != 'manual' and c['topic'] == topic and c['product_id'] == product_id), key=lambda c: c['created_at'], reverse=True)
                if not evidence_ids or (previous and not (set(evidence_ids) - set(previous[0].get('evidence_ids') or []))):
                    return None
            local_day = datetime.now(ZoneInfo(settings['timezone'])).date().isoformat() if trigger == 'daily' else None
            if local_day and any(c['org_id'] == org and c.get('daily_key') == local_day for c in self.state['campaigns'].values()):
                return None
            if automatic and any(c['org_id'] == org and c['trigger'] != 'manual' and c['topic'] == topic and c['product_id'] == product_id
                    and datetime.fromisoformat(c['created_at']).timestamp() > time.time() - settings['cooldown_hours'] * 3600 for c in self.state['campaigns'].values()):
                return None
            row = dict(id=_id(), org_id=org, revision=1, status='queued', script_status='pending', artifact=None,
                       compliance={}, missing_evidence=[], build_status=None, trigger=trigger, prompt=prompt,
                       language=language, topic=topic, product_id=product_id, dedup_key=key or _id(), result=None,
                       created_at=_now(), updated_at=_now(), daily_key=local_day, evidence_ids=deepcopy(evidence_ids or []))
            self.state['campaigns'][row['id']] = row
            _job(self.state, org, 'generate', {'campaign_id': row['id']}, row['id'], row['id'])
            return deepcopy(row)

    async def list_campaigns(self, org):
        if not self.memory:
            return await self._rpc('list', org=org)
        return deepcopy(sorted((c for c in self.state['campaigns'].values() if c['org_id'] == org), key=lambda c: c['created_at'], reverse=True))

    async def get_campaign(self, org, id):
        if not self.memory:
            return await self._rpc('get', org=org, id=id)
        row = self.state['campaigns'].get(id)
        return deepcopy(row) if row and row['org_id'] == org else None

    def _campaign_status(self, job, status):
        variant_id = job.get('payload', {}).get('variant_id')
        if variant_id:
            from services.vea.store import _state as vea_state
            variant = vea_state(self.repo)['variants'].get(variant_id)
            if variant:
                variant.update(status={'running':'rendering'}.get(status,status),
                               error=(job.get('payload',{}).get('render_error') or job.get('last_error')) if status=='failed' else None,updated_at=_now())
                if not variant['is_default']:
                    return
        c = self.state['campaigns'].get(job.get('campaign_id'))
        if c:
            c['build_status' if job['kind'] == 'build' else 'status'] = status
            c['updated_at'] = _now()

    async def claim(self, kind, limit=1, lease_seconds=600):
        if kind not in ('extract', 'generate', 'build'):
            raise ValueError('Invalid job kind')
        if not self.memory:
            return await self._rpc('claim', kind=kind, limit=limit, lease_seconds=lease_seconds)
        async with self.repo._lock:
            result = []
            for j in self.state['jobs'].values():
                if j['kind'] != kind:
                    continue
                expired = j['status'] == 'leased' and j['lease_until'] <= time.time()
                if expired and j['attempts'] >= 3:
                    j.update(status='failed', lease_token=None, lease_until=None, last_error='Worker retries exhausted')
                    self._campaign_status(j, 'failed')
                if j['attempts'] >= 3 or not ((j['status'] == 'pending' and j['available_at'] <= time.time()) or expired):
                    continue
                j.update(status='leased', attempts=j['attempts']+1, lease_token=_id(), lease_until=time.time()+max(10, min(lease_seconds, 3600)))
                self._campaign_status(j, 'running' if kind == 'build' else 'generating')
                result.append(deepcopy(j))
                if len(result) >= max(1, min(limit, 100)):
                    break
            return result

    def _leased(self, job):
        row = self.state['jobs'].get(job['id'])
        if not row or row['org_id'] != job['org_id'] or row['status'] != 'leased' or row['lease_token'] != job['lease_token'] or row['lease_until'] <= time.time():
            raise WorkflowConflict('Milo worker lease expired')
        return row

    def _done(self, row):
        row.update(status='completed', lease_token=None, lease_until=None, last_error=None)

    async def finish_extraction(self, job, items):
        if not self.memory:
            return await self._rpc('extracted', job=job['id'], token=job['lease_token'], items=items)
        async with self.repo._lock:
            j = self._leased(job)
            if j['kind'] != 'extract':
                raise WorkflowConflict('Wrong job kind')
            payload = j['payload']
            for item in items:
                start, end = item['span_start'], item['span_end']
                if type(start) is not int or type(end) is not int or start < 0 or end <= start or payload['text'][start:end] != item['buyer_text'] or not item.get('topic'):
                    raise WorkflowConflict('Buyer quote is not an exact source span')
                if item.get('product_id') is not None and not any(p.get('id') == item['product_id'] and p.get('org_id') == j['org_id'] and not p.get('deleted_at') for p in getattr(self.repo, 'brand_products', [])):
                    raise WorkflowConflict('Objection product is not in this brand catalog')
            for item in items:
                key = (payload['inbound_id'], item['objection_type'], item['span_start'], item['span_end'])
                if key not in self.state['objections']:
                    self.state['objections'][key] = dict(id=_id(), org_id=j['org_id'], inbound_id=payload['inbound_id'], prospect_id=payload['prospect_id'],
                        created_at=payload['received_at'], **deepcopy(item))
            self._done(j)
            return True

    async def objections(self, org, since_iso):
        if not self.memory:
            return await self._rpc('objections', org=org, since=since_iso)
        since = datetime.fromisoformat(since_iso.replace('Z', '+00:00'))
        return deepcopy([v for v in self.state['objections'].values() if v['org_id'] == org and datetime.fromisoformat(v['created_at'].replace('Z', '+00:00')) >= since])

    async def complete_generation(self, job, artifact, compliance, missing_evidence=None, *, selected_scope=None):
        if selected_scope is not None and (
                not isinstance(selected_scope, dict) or set(selected_scope) != {'product_id', 'topic'} or
                selected_scope['topic'] not in TOPICS or
                (selected_scope['product_id'] is not None and
                 (not isinstance(selected_scope['product_id'], str) or not selected_scope['product_id'].strip()))):
            raise WorkflowConflict('Invalid generation scope')
        if not self.memory:
            return await self._rpc('generated', job=job['id'], token=job['lease_token'], artifact=artifact, compliance=compliance,
                                   missing=missing_evidence or [], selected_scope=selected_scope)
        async with self.repo._lock:
            j = self._leased(job)
            if j['kind'] != 'generate':
                raise WorkflowConflict('Wrong job kind')
            c = self.state['campaigns'][j['campaign_id']]
            if selected_scope is not None:
                if ((c.get('topic') is not None and
                     (c['topic'], c.get('product_id')) != (selected_scope['topic'], selected_scope['product_id'])) or
                    (c.get('product_id') is not None and c['product_id'] != selected_scope['product_id'])):
                    raise WorkflowConflict('Generation scope differs from the reserved evidence')
                c.update(deepcopy(selected_scope))
            c.update(artifact=deepcopy(artifact), compliance=deepcopy(compliance), missing_evidence=deepcopy(missing_evidence or []),
                     status='needs_evidence' if missing_evidence else ('awaiting_review' if compliance.get('passed') else 'blocked'), revision=c['revision']+1, updated_at=_now())
            self._done(j)
            return deepcopy(c)

    def _check_evidence(self, org, artifact):
        passport = self.repo.brand_passports.get(org, {})
        if artifact.get('brand_revision') != passport.get('revision', 1):
            raise WorkflowConflict('Brand evidence changed')
        # Memory repositories may expose explicit source fixtures for parity tests.
        sources = getattr(self.repo, 'memory_sources', [])
        if isinstance(sources, dict):
            sources = sources.values()
        for ref in artifact.get('proof_references', []):
            source = next((s for s in sources if s['id'] == ref['source_id'] and s['org_id'] == org), None)
            if not source or source.get('deleted_at') or source.get('forgotten_at') or source['revision'] != ref['revision'] or not ref.get('quote') or ref['quote'] not in source.get('content', ''):
                raise WorkflowConflict('Proof evidence changed')

    async def renew(self, job, lease_seconds=600):
        if not self.memory:
            return await self._rpc('renew', job=job['id'], token=job['lease_token'], lease_seconds=lease_seconds)
        async with self.repo._lock:
            row = self._leased(job)
            row['lease_until'] = time.time()+max(10, min(lease_seconds, 3600))
            return deepcopy(row)

    async def decide_script(self, org, id, action, expected_revision, key, script=None, compliance=None):
        if action not in ('edit', 'approve', 'reject') or not key:
            raise ValueError('Valid decision and idempotency key required')
        if not self.memory:
            return await self._rpc('decide', org=org, id=id, action=action, revision=expected_revision, key=key, script=script, compliance=compliance)
        async with self.repo._lock:
            fingerprint = json.dumps([id, action, expected_revision, script], sort_keys=True)
            previous = self.state['decisions'].get((org, key))
            if previous:
                if previous[0] != fingerprint:
                    raise WorkflowConflict('Idempotency key reused')
                return deepcopy(previous[1])
            c = self.state['campaigns'].get(id)
            if not c or c['org_id'] != org or c['revision'] != expected_revision or c['status'] not in ('awaiting_review', 'blocked') or c['script_status'] != 'pending':
                raise WorkflowConflict('Campaign revision or organization conflict')
            if action == 'approve':
                checks = compliance if compliance is not None else c['compliance']
                if not checks.get('passed') or not checks.get('semantic_checked') or checks.get('checked_brand_revision') != c['artifact'].get('brand_revision') or c['missing_evidence']:
                    raise WorkflowConflict('Campaign requires compliance review')
                self._check_evidence(org, c['artifact'])
                c.update(script_status='approved', build_status='queued', compliance=deepcopy(checks))
                _job(self.state, org, 'build', dict(campaign_id=id, script_revision=expected_revision,
                     video_script=deepcopy(c['artifact']['video_script']), language=c['artifact'].get('language') or c.get('language') or 'en',
                     submission_state='not_submitted', provider_attempt=1), f'{id}:{expected_revision}', id)
            elif action == 'edit':
                if not isinstance(script, list) or not script:
                    raise ValueError('Video script must contain scenes')
                c['artifact']['video_script'] = deepcopy(script)
                c.update(compliance=deepcopy(compliance or {}), status='awaiting_review' if (compliance or {}).get('passed') else 'blocked')
            else:
                c['script_status'] = 'rejected'
            c.update(revision=c['revision']+1, updated_at=_now())
            self.state['decisions'][(org, key)] = fingerprint, deepcopy(c)
            return deepcopy(c)

    async def update_build(self, job, values):
        if not self.memory:
            return await self._rpc('update_build', job=job['id'], token=job['lease_token'], values=values)
        async with self.repo._lock:
            j = self._leased(job)
            if j['kind'] != 'build':
                raise WorkflowConflict('Wrong job kind')
            if values.get('submission_state') in ('submission_started', 'submitting') and not (j['payload'].get('provider_task_id') or j['payload'].get('task_id')):
                self._check_evidence(j['org_id'], self.state['campaigns'][j['campaign_id']]['artifact'])
            j['payload'].update(deepcopy(values))
            return deepcopy(j)

    async def complete_build(self, job, result):
        if job.get('payload', {}).get('variant_id'):
            from services.vea.store import VeaStore
            return await VeaStore(self.repo).complete(job,result)
        if not self.memory:
            return await self._rpc('built', job=job['id'], token=job['lease_token'], result=result)
        async with self.repo._lock:
            j = self._leased(job)
            if j['kind'] != 'build':
                raise WorkflowConflict('Wrong job kind')
            d = await self.repo.create_draft(j['org_id'], 'vea', 'Milo approved video script', json.dumps(result, ensure_ascii=False))
            from services.workflow.state import apply_transition
            draft = next(draft for draft in self.repo.drafts if draft['id'] == d['id'])
            draft.update(apply_transition(draft, 'ready', edited_content=json.dumps(result, ensure_ascii=False)))
            self.repo._event(j['org_id'], 'draft_transition', draft)
            c = self.state['campaigns'][j['campaign_id']]
            c.update(build_status='completed', result={**deepcopy(result), 'draft_id': d['id']}, updated_at=_now())
            self._done(j)
            return deepcopy(c)

    async def fail(self, job, error):
        if not self.memory:
            return await self._rpc('fail', job=job['id'], token=job['lease_token'], error=error)
        async with self.repo._lock:
            try:
                j = self._leased(job)
            except WorkflowConflict:
                return False
            ambiguous = j['kind'] == 'build' and j['payload'].get('submission_state') in ('submitting', 'submission_started', 'ambiguous') and not (j['payload'].get('provider_task_id') or j['payload'].get('task_id'))
            if ambiguous:
                j['payload']['submission_state'] = 'ambiguous'
            unavailable=error=='LanguageServiceUnavailable'
            provider_failed=j['kind']=='build' and j['payload'].get('submission_state')=='provider_failed'
            j.update(status='failed' if j['attempts'] >= 3 or ambiguous or unavailable or provider_failed else 'pending', lease_token=None, lease_until=None,
                     available_at=time.time()+5*2**j['attempts'], last_error=(
                         'The configured language service is temporarily unavailable. Retry after provider recovery.' if unavailable else
                         'Milo processing failed; retry available.'))
            self._campaign_status(j, 'failed' if j['status'] == 'failed' else 'queued')
            return True

    def _replay(self, org, key, fingerprint):
        previous = self.state['decisions'].get((org, key)) if key else None
        if previous:
            if previous[0] != fingerprint:
                raise WorkflowConflict('Idempotency key reused with a different request')
            return deepcopy(previous[1])
        return None

    def _receipt(self, org, key, fingerprint, row):
        if key:
            self.state['decisions'][(org, key)] = fingerprint, deepcopy(row)
        return deepcopy(row)

    async def replay_reconcile(self, org, job_id, task_id, key):
        """Read a committed receipt before contacting a potentially unavailable provider."""
        if not key:
            raise ValueError('Idempotency key required')
        if not self.memory:
            return await self._rpc('replay_reconcile', org=org, id=job_id, task_id=task_id, key=key)
        async with self.repo._lock:
            return self._replay(org, key, json.dumps(['reconcile', job_id, task_id], sort_keys=True))

    async def reconcile_build(self, org, job_id, task_id, key=None):
        if not str(task_id or '').strip():
            raise ValueError('Provider task ID required')
        if not self.memory:
            return await self._rpc('reconcile', org=org, id=job_id, task_id=task_id, key=key)
        async with self.repo._lock:
            fingerprint = json.dumps(['reconcile', job_id, task_id], sort_keys=True)
            previous = self._replay(org, key, fingerprint)
            if previous is not None:
                return previous
            j = self.state['jobs'].get(job_id)
            if not j or j['org_id'] != org or j['kind'] != 'build' or j['status'] != 'failed' or j['payload'].get('provider_task_id') or j['payload'].get('task_id') or j['payload'].get('submission_state') not in ('submitting', 'submission_started', 'ambiguous'):
                raise WorkflowConflict('Build does not require a submission receipt')
            j['payload'].update(provider_task_id=task_id, task_id=task_id, submission_state='submitted')
            j.update(status='pending', attempts=0, available_at=0, lease_token=None, lease_until=None, last_error=None)
            self._campaign_status(j, 'queued')
            return self._receipt(org, key, fingerprint, j)

    async def retry(self, org, job_id, key=None):
        if not self.memory:
            return await self._rpc('retry', org=org, id=job_id, key=key)
        async with self.repo._lock:
            fingerprint = json.dumps(['retry', job_id], sort_keys=True)
            previous = self._replay(org, key, fingerprint)
            if previous is not None:
                return previous
            j = self._retry_locked(org, job_id)
            return self._receipt(org, key, fingerprint, j)

    def _retry_locked(self, org, job_id):
        """Reuse the uncertainty fence from transactional variant retry."""
        j = self.state['jobs'].get(job_id)
        if not j or j['org_id'] != org or j['status'] != 'failed':
            raise WorkflowConflict('Only failed jobs can be retried')
        if j['kind'] == 'build' and j['payload'].get('submission_state') in ('submitting', 'submission_started', 'ambiguous') and not (j['payload'].get('provider_task_id') or j['payload'].get('task_id')):
            raise WorkflowConflict('Build requires provider receipt reconciliation before retry')
        if j['kind'] == 'build' and j['payload'].get('submission_state') == 'provider_failed':
            payload = j['payload']
            attempt = payload.get('provider_attempt', 1)
            payload.setdefault('provider_attempts', []).append(dict(provider_attempt=attempt,
                provider_task_id=payload.get('provider_task_id') or payload.get('task_id'),
                submission_state='provider_failed', finished_at=_now()))
            payload.pop('provider_task_id', None)
            payload.pop('task_id', None)
            payload.update(submission_state='not_submitted', provider_attempt=attempt+1)
        j.update(status='pending', attempts=0, available_at=0, lease_token=None, lease_until=None, last_error=None)
        self._campaign_status(j, 'queued')
        return j

    async def jobs(self, org):
        if not self.memory:
            return await self._rpc('jobs', org=org)
        return deepcopy([j for j in self.state['jobs'].values() if j['org_id'] == org])

    async def organizations(self):
        if not self.memory:
            return await self._rpc('organizations')
        return sorted(set(self.repo.brand_passports) | set(self.state['settings']))
