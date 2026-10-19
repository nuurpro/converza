"""Durable, leased SLEYZ inbox and approved-edit learning boundary."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import time
import uuid

from starlette.concurrency import run_in_threadpool
from services.workflow.state import WorkflowConflict, apply_transition


def _id():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc).isoformat()


def _state(repo):
    if not hasattr(repo, '_sleyz_state'):
        repo._sleyz_state = {k: {} for k in ('inbox', 'prospects', 'learning', 'refresh')}
        repo._sleyz_state.update(telemetry=[], corrections=[])
    return repo._sleyz_state


def enqueue_approved_edit(repo, row):
    """Called while the repository transaction lock is held, before its event."""
    if (row.get('status') != 'EDITED' or row.get('agent_slug') != 'sleyz'
            or row.get('simulated') or not row.get('sleyz_artifact')
            or row.get('final_content') == row.get('draft_content')):
        return
    state = _state(repo)
    if any(j['draft_id'] == row['id'] and j['approved_revision'] == row['revision'] for j in state['learning'].values()):
        return
    job = dict(id=_id(), org_id=row['org_id'], draft_id=row['id'],
        original_content=row['draft_content'], final_content=row['final_content'],
        approved_revision=row['revision'], approved_at=row['decided_at'],
        status='pending', attempts=0, available_at=0, lease_token=None, lease_until=None)
    state['learning'][job['id']] = job
    row['learning_status'] = 'pending'


class SleyzStore:
    def __init__(self, repo):
        self.repo = repo
        self.memory = not hasattr(repo, 'client')
        if self.memory:
            self.state = _state(repo)

    async def _rpc(self, name, **params):
        try:
            result = await run_in_threadpool(self.repo.client.rpc(name, params).execute)
            return result.data
        except Exception as exc:
            if 'workflow_conflict' in str(exc) or 'workflow_not_found' in str(exc):
                raise WorkflowConflict('SLEYZ revision, lease, or organization conflict') from exc
            raise

    async def accept(self, envelope):
        required = ('org_id', 'connection_id', 'external_message_id', 'customer_id', 'text', 'received_at')
        if any(not str(envelope.get(k) or '').strip() for k in required) or envelope.get('platform') not in ('telegram', 'instagram'):
            raise ValueError('Invalid inbound envelope')
        if len(envelope['text']) > 16000:
            raise ValueError('Inbound text exceeds 16000 characters')
        envelope = deepcopy(envelope)
        envelope.setdefault('simulated', False)
        envelope['customer_handle'] = envelope.get('customer_handle') or str(envelope['customer_id'])
        if not self.memory:
            return await self._rpc('sleyz_accept_inbound', p_envelope=envelope)
        async with self.repo._lock:
            return await self._accept_memory(envelope)

    async def _accept_memory(self, envelope):
        key = tuple(str(envelope[k]) for k in ('org_id', 'connection_id', 'platform', 'external_message_id'))
        existing = next((j for j in self.state['inbox'].values() if j['dedup_key'] == key), None)
        if existing:
            return dict(inbound_id=existing['id'], draft_id=existing['draft_id'], duplicate=True)
        prospect_key = tuple(str(envelope[k]) for k in ('org_id', 'platform', 'customer_id'))
        if envelope.get('simulated'):
            prospect_key += ('simulated',)
        prospect = self.state['prospects'].setdefault(prospect_key, dict(id=_id(), org_id=envelope['org_id']))
        prospect.update(platform=envelope['platform'], external_id=envelope['customer_id'], customer_handle=envelope['customer_handle'],
            tg_chat_id=envelope.get('tg_chat_id'), business_connection_id=envelope.get('business_connection_id'),
            metadata={'connection_id': envelope['connection_id'], 'received_at': envelope['received_at']})
        inbound_id = _id()
        draft = await self.repo.create_draft(envelope['org_id'], 'sleyz', envelope['text'], '', prospect['id'])
        row = next(d for d in self.repo.drafts if d['id'] == draft['id'])
        row.update(sleyz_artifact=None, simulated=envelope['simulated'], platform=envelope['platform'],
            inbound_id=inbound_id, superseded_by=None, learning_status=None, learning_error=None)
        # Replace the creation event with the complete transactional row.
        self.repo.events[-1]['payload']['row'] = deepcopy(row)
        self.state['inbox'][inbound_id] = dict(id=inbound_id, org_id=envelope['org_id'], draft_id=draft['id'], prospect_id=prospect['id'], received_at=envelope['received_at'],
            envelope=envelope, dedup_key=key, status='pending', attempts=0, available_at=0, lease_until=None, lease_token=None)
        from services.milo.store import enqueue_inbound
        enqueue_inbound(self.repo, self.state['inbox'][inbound_id])
        return dict(inbound_id=inbound_id, draft_id=draft['id'], duplicate=False)

    async def _claim(self, learning, limit, lease_seconds):
        if not self.memory:
            return await self._rpc('sleyz_claim_learning' if learning else 'sleyz_claim_jobs', p_limit=limit, p_lease_seconds=lease_seconds) or []
        async with self.repo._lock:
            results, now = [], time.time()
            for job in self.state['learning' if learning else 'inbox'].values():
                expired = job['status'] == 'leased' and job['lease_until'] <= now
                if expired and job['attempts'] >= 3:
                    job.update(status='failed', lease_token=None, lease_until=None, last_error='Worker lease expired after maximum attempts')
                    self._draft_status(job, learning, 'failed', 'Worker lease expired after maximum attempts')
                if job['attempts'] >= 3 or not ((job['status'] == 'pending' and job['available_at'] <= now) or expired):
                    continue
                job.update(status='leased', lease_token=_id(), lease_until=now + max(10, min(lease_seconds, 3600)), attempts=job['attempts'] + 1)
                self._draft_status(job, learning, 'running')
                results.append(deepcopy(job))
                if len(results) >= max(1, min(limit, 100)):
                    break
            return results

    async def claim(self, limit=1, lease_seconds=600):
        return await self._claim(False, limit, lease_seconds)

    async def claim_learning(self, limit=1, lease_seconds=600):
        return await self._claim(True, limit, lease_seconds)

    def _draft(self, job):
        return next(d for d in self.repo.drafts if d['id'] == job['draft_id'] and d['org_id'] == job['org_id'])

    def _draft_status(self, job, learning, status, error=None):
        draft = self._draft(job)
        draft['learning_status' if learning else 'generation_status'] = status
        draft['learning_error' if learning else 'generation_error'] = error
        draft.update(revision=draft['revision'] + 1, updated_at=_now())
        self.repo._event(job['org_id'], 'draft_transition', draft)

    def _leased(self, collection, job):
        current = self.state[collection].get(job['id'])
        if not current or current['status'] != 'leased' or current['lease_token'] != job['lease_token'] or current['lease_until'] <= time.time():
            return None
        return current

    async def ready(self, job, artifact):
        if not str(artifact.get('draft_reply') or '').strip():
            raise ValueError('Generated reply is empty')
        if not self.memory:
            return await self._rpc('sleyz_ready_job', p_job=job['id'], p_token=job['lease_token'], p_artifact=artifact)
        async with self.repo._lock:
            current = self._leased('inbox', job)
            if not current:
                raise WorkflowConflict('Worker lease expired')
            draft = self._draft(job)
            draft.update(apply_transition(draft, 'ready', edited_content=artifact['draft_reply']))
            draft['sleyz_artifact'] = deepcopy(artifact)
            current.update(status='completed', lease_token=None, lease_until=None)
            self.repo._event(job['org_id'], 'draft_transition', draft)
            await self.repo.insert_squad_message(job['org_id'], 'sleyz', 'Inbound reply ready for review', hitl_draft_id=draft['id'])
            return deepcopy(draft)

    async def _fail(self, learning, job):
        message = 'Learning analysis failed; retry available.' if learning else 'Draft generation failed; retry available.'
        if not self.memory:
            return await self._rpc('sleyz_fail_learning' if learning else 'sleyz_fail_job', p_job=job['id'], p_token=job['lease_token'], p_error=message)
        async with self.repo._lock:
            current = self._leased('learning' if learning else 'inbox', job)
            if not current:
                return False
            status = 'failed' if current['attempts'] >= 3 else 'pending'
            current.update(status=status, lease_token=None, lease_until=None, available_at=time.time() + 5 * 2 ** current['attempts'], last_error=message)
            self._draft_status(job, learning, status, message)
            return True

    async def fail(self, job, error):
        return await self._fail(False, job)

    async def fail_learning(self, job, error):
        return await self._fail(True, job)

    async def complete_learning(self, job, correction):
        if not self.memory:
            return await self._rpc('sleyz_complete_learning', p_job=job['id'], p_token=job['lease_token'], p_correction=correction)
        async with self.repo._lock:
            current = self._leased('learning', job)
            if not current:
                return False
            if correction:
                rule = correction.get('rule') or correction.get('content')
                metadata = {k: current[k] for k in ('draft_id', 'approved_revision', 'approved_at', 'original_content', 'final_content')}
                metadata.update(priority=2, supporting_spans=correction.get('supporting_spans', []), rule_type=correction.get('rule_type'))
                source_id = _id()
                atom = dict(kind='correction', text=rule, source_id=source_id, source_revision=1, span=[0,len(rule)], **metadata)
                self.state['corrections'].append(dict(id=source_id, org_id=current['org_id'], kind='correction',
                    external_id=f"{current['draft_id']}:{current['approved_revision']}", title='Approved reply correction', content=rule,
                    metadata=metadata, atoms=[atom], summary=rule, revision=1, indexed_revision=1, indexing_status='ready', updated_at=current['approved_at']))
            current.update(status='completed', lease_token=None, lease_until=None)
            self._draft_status(job, True, 'completed' if correction else 'skipped')
            return True

    async def retry_learning(self, org, draft_id):
        if not self.memory:
            return await self._rpc('sleyz_retry_learning', p_org=org, p_draft=draft_id)
        async with self.repo._lock:
            job = next((j for j in self.state['learning'].values() if j['draft_id'] == draft_id and j['org_id'] == org and j['status'] == 'failed'), None)
            if not job:
                raise WorkflowConflict('No failed learning job')
            job.update(status='pending', attempts=0, available_at=0, lease_token=None, lease_until=None, last_error=None)
            self._draft_status(job, True, 'pending')
            return deepcopy(job)

    async def retry_generation(self, org, draft_id, expected_revision, idempotency_key):
        if not idempotency_key:
            raise ValueError('idempotency_key required')
        if not self.memory:
            return await self._rpc('sleyz_retry_generation',p_org=org,p_draft=draft_id,p_revision=expected_revision,p_key=idempotency_key)
        async with self.repo._lock:
            cache_key = (org,idempotency_key)
            fingerprint = ('sleyz_retry_generation',draft_id,expected_revision)
            if cache_key in self.repo.idempotency:
                prior,result = self.repo.idempotency[cache_key]
                if prior != fingerprint:
                    raise WorkflowConflict('Idempotency key reused')
                return deepcopy(result)
            draft = next((d for d in self.repo.drafts if d['org_id']==org and d['id']==draft_id),None)
            job = self.state['inbox'].get(draft.get('inbound_id')) if draft else None
            if not draft or draft['revision']!=expected_revision or draft['status']!='PENDING_DRAFT' or draft.get('generation_status')!='failed' or not job or job['status']!='failed':
                raise WorkflowConflict('No failed inbound generation at this revision')
            job.update(status='pending',attempts=0,available_at=0,lease_token=None,lease_until=None,last_error=None)
            self._draft_status(job,False,'pending')
            self.repo.idempotency[cache_key] = (fingerprint,deepcopy(draft))
            return deepcopy(draft)

    async def telemetry(self, job, objections):
        if not self.memory:
            await self._rpc('sleyz_telemetry', p_job=job['id'], p_objections=objections)
            return
        async with self.repo._lock:
            current = self.state['inbox'].get(job['id'])
            if not current or current['org_id'] != job['org_id']:
                raise WorkflowConflict('Inbound organization mismatch')
            for item in objections:
                start, end = item['span']
                if not 0 <= start < end <= len(current['envelope']['text']) or current['envelope']['text'][start:end] != item['text']:
                    raise WorkflowConflict('Invalid objection span')
            for item in objections:
                entry = dict(org_id=job['org_id'], inbound_id=job['id'], draft_id=job['draft_id'], prospect_id=self._draft(job)['prospect_id'], **item)
                entry['span'] = list(entry['span'])
                if entry not in self.state['telemetry']:
                    self.state['telemetry'].append(entry)

    async def refresh(self, org, draft_id, expected_revision, idempotency_key):
        if not idempotency_key:
            raise ValueError('idempotency_key required')
        if not self.memory:
            return await self._rpc('sleyz_refresh', p_org=org, p_draft=draft_id, p_revision=expected_revision, p_key=idempotency_key)
        async with self.repo._lock:
            cached = self.repo.idempotency.get((org, idempotency_key))
            request = ('sleyz_refresh', draft_id, expected_revision)
            if cached:
                if cached[0] != request:
                    raise WorkflowConflict('Idempotency key reused')
                return deepcopy(cached[1])
            draft = next((d for d in self.repo.drafts if d['id'] == draft_id and d['org_id'] == org), None)
            if not draft or draft['revision'] != expected_revision or draft.get('superseded_by') or draft['status'] not in ('AWAITING_HITL', 'APPROVED', 'EDITED') or draft.get('delivery_status') in ('sending', 'ambiguous', 'delivered'):
                raise WorkflowConflict('Draft cannot be refreshed')
            envelope = deepcopy(self.state['inbox'][draft['inbound_id']]['envelope'])
            envelope['external_message_id'] += ':refresh:' + idempotency_key
            result = await self._accept_memory(envelope)
            draft.update(superseded_by=result['draft_id'], revision=draft['revision'] + 1, updated_at=_now())
            self.repo._event(org, 'draft_transition', draft)
            self.repo.idempotency[(org, idempotency_key)] = (request, deepcopy(result))
            return result
