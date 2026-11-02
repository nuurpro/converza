"""Durable director boundary using versioned SQL CAS and atomic outbox events.

All state mutations are reduced locally, then committed under an organization
lock with an expected aggregate version. Competing workers retry from a fresh
snapshot. SQL projects immutable attempts, tokens, revisions and queue intents.
"""
from copy import deepcopy
import asyncio
import json
import time
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool
from services.workflow.state import WorkflowConflict
from .state import uid, digest, new_run, fenced, event, fail_task, complete_task


class DirectorStore:
    def __init__(self, repo):
        self.repo = repo
        self.memory = not hasattr(repo, 'client')
        if self.memory:
            if not hasattr(repo, '_milo_director'):
                repo._milo_director = {}
            self.rows = repo._milo_director

    async def _rpc(self, action, **args):
        try:
            response = await run_in_threadpool(self.repo.client.rpc('milo_director_store',
                {'p_action': action, 'p_args': args}).execute)
            return response.data
        except Exception as exc:
            if 'workflow_conflict' in str(exc) or 'workflow_not_found' in str(exc):
                raise WorkflowConflict('Director ownership, revision, or lease conflict') from exc
            raise

    async def get(self, org, run_id):
        if not self.memory:
            row = await self._rpc('get', org=org, id=run_id)
        else:
            row = self.rows.get(run_id)
            if row and row['org_id'] != org:
                row = None
        if not row:
            raise WorkflowConflict('Director run not found')
        return deepcopy(row)

    async def list_for_campaign(self, org, campaign_id):
        if not self.memory:
            return await self._rpc('list', org=org, campaign_id=campaign_id)
        return deepcopy(sorted([r for r in self.rows.values() if r['org_id']==org and
            r['campaign_id']==campaign_id], key=lambda r:r['created_at'], reverse=True))

    async def _commit(self, row, expected, *, parent_version=None, fence=None):
        if not self.memory:
            return await self._rpc('commit', org=row['org_id'], row=row,
                                   expected=expected, parent_version=parent_version, fence=fence)
        async with self.repo._lock:
            previous = self.rows.get(row['id'])
            if previous and expected!=-1 and (row.get('reuse_context')!=previous.get('reuse_context') or
                row.get('reuse_context_hash')!=previous.get('reuse_context_hash')):
                raise WorkflowConflict('Immutable director renderer context')
            for key,receipt in row.get('recovery_receipts',{}).items():
                for stored in self.rows.values():
                    prior=stored.get('recovery_receipts',{}).get(key) if stored['org_id']==row['org_id'] else None
                    if prior and prior['fingerprint']!=receipt['fingerprint']:
                        raise WorkflowConflict('Director recovery idempotency key reused')
            if expected == -1:
                campaign=getattr(self.repo,'_milo_state',{}).get('campaigns',{}).get(row['campaign_id'])
                if campaign and (campaign['org_id']!=row['org_id'] or campaign.get('product_id')!=row.get('product_id') or
                    (row['script_approved'] and (campaign['script_status']!='approved' or campaign['revision']!=row['approved_revision']))):
                    raise WorkflowConflict('Director campaign approval or product scope changed')
                document=getattr(self.repo,'_director_documents',{}).get((row['org_id'],row['campaign_id']))
                if document:
                    board=document['storyboard']
                    if (board['revision']!=row['storyboard_revision'] or
                        board['scenes']!=[s['specification'] for s in row['scenes']] or
                        (row['script_approved'] and not board['narration_approved']) or
                        document['campaign_revision']!=row['approved_revision']):
                        raise WorkflowConflict('Director storyboard approval changed')
                duplicate = next((r for r in self.rows.values() if r['org_id']==row['org_id'] and
                    r['campaign_id']==row['campaign_id'] and r['key']==row['key']), None)
                if duplicate:
                    if duplicate['request_hash'] != row['request_hash']:
                        raise WorkflowConflict('Director idempotency key reused')
                    return deepcopy(duplicate)
                parent = self.rows.get(row.get('parent_run_id'))
                if parent:
                    if parent['version'] != parent_version or parent.get('superseded_by'):
                        return None
                    parent['superseded_by'] = row['id']
                    event(parent,'SUPERSEDED','New storyboard production supersedes this run')
                    parent['version'] += 1
                    await self.repo.insert_agent_run_step(parent['id'],row['org_id'],'milo','SUPERSEDED','completed',
                        json.dumps(parent['progress'][-1],ensure_ascii=False))
                    for draft in self.repo.drafts:
                        if draft['org_id']==row['org_id'] and draft['id']==parent.get('draft_id'):
                            draft['director_artifact']={**draft.get('director_artifact',{}),'superseded':True,'superseded_by':row['id']}
                            self.repo._event(row['org_id'],'draft_transition',draft)
                self.repo.agent_runs.append(dict(id=row['id'],org_id=row['org_id'],agent_slug='milo',
                    triggered_by='agent',input_text='Autonomous video director',status='running'))
            elif not previous or previous['version'] != expected or previous.get('superseded_by') or previous.get('document_fenced'):
                return None
            old_progress = len(previous.get('progress', [])) if previous else 0
            row['version'] = expected+1
            self.rows[row['id']] = deepcopy(row)
            for progress in row['progress'][old_progress:]:
                await self.repo.insert_agent_run_step(row['id'], row['org_id'], 'milo',
                    progress['state'], 'failed' if progress['state']=='BLOCKED' else 'completed',
                    json.dumps(progress, ensure_ascii=False))
            if row.get('draft_id') and not any(d['id']==row['draft_id'] for d in self.repo.drafts):
                draft = dict(id=row['draft_id'], org_id=row['org_id'], agent_slug='vea',
                    inbound_text='Milo recommends approval · automated checks passed',
                    draft_content=json.dumps(dict(**row['master_result'], inspection_report=row['inspection_report'],
                        director_run_id=row['id']),ensure_ascii=False),status='AWAITING_HITL',
                    director_artifact={**row['master_result'],'director_run_id':row['id'],
                        'inspection':{'passed':True},'inspection_report':row['inspection_report']},
                    revision=1,generation_status='completed',delivery_status='idle',
                    final_content=None,generation_error=None,delivery_error=None,delivery_receipt=None,
                    delivered_at=None,resolved_at=None,created_at=datetime.now(timezone.utc).isoformat())
                self.repo.drafts.append(draft)
                self.repo._event(row['org_id'], 'draft_transition', draft)
            if row.get('draft_id'):
                for run in self.repo.agent_runs:
                    if run['id']==row['id']: run['status']='awaiting_hitl'
                campaign=getattr(self.repo,'_milo_state',{}).get('campaigns',{}).get(row['campaign_id'])
                if campaign:
                    campaign['build_status']='completed'
                    campaign['result']={**(campaign.get('result') or {}),'draft_id':row['draft_id'],'director_run_id':row['id']}
            elif row['state']=='BLOCKED':
                for run in self.repo.agent_runs:
                    if run['id']==row['id']: run['status']='failed'
                campaign=getattr(self.repo,'_milo_state',{}).get('campaigns',{}).get(row['campaign_id'])
                if campaign: campaign['build_status']='failed'
            return deepcopy(row)

    async def create_run(self, org, campaign_id, approved_revision, scenes, key, *,
                         script_approved=True, parent_run_id=None, storyboard_revision=None,
                         language='en', transitions=None,reuse_context=None,background_asset_id=None,product_id=None):
        if not key or not str(key).strip():
            raise ValueError('Director idempotency key required')
        request_hash = digest(dict(approved_revision=approved_revision,scenes=scenes,
            script_approved=script_approved,parent_run_id=parent_run_id,
            storyboard_revision=storyboard_revision,language=language,transitions=transitions,reuse_context=reuse_context,
            background_asset_id=background_asset_id,product_id=product_id))
        for _ in range(30):
            existing = await self.list_for_campaign(org,campaign_id)
            duplicate = next((r for r in existing if r['key']==key),None)
            if duplicate:
                if duplicate['request_hash'] != request_hash:
                    raise WorkflowConflict('Director idempotency key reused')
                return duplicate
            parent = await self.get(org,parent_run_id) if parent_run_id else None
            if parent and (parent['campaign_id']!=campaign_id or parent.get('superseded_by')):
                raise WorkflowConflict('Invalid director revision parent')
            # Only one active revision per campaign. Explicit branches supersede it.
            if not parent and any(not r.get('superseded_by') for r in existing):
                raise WorkflowConflict('A director run already exists; create a revision branch')
            row = new_run(org,campaign_id,approved_revision,scenes,key,script_approved=script_approved,
                parent=parent,storyboard_revision=storyboard_revision,language=language,transitions=transitions,reuse_context=reuse_context,
                background_asset_id=background_asset_id,product_id=product_id)
            row['request_hash'] = request_hash
            committed = await self._commit(row,-1,parent_version=parent['version'] if parent else None)
            if committed:
                return committed
            await asyncio.sleep(0)
        raise WorkflowConflict('Director revision contention')

    async def _mutate(self, org, run_id, operation, *, fence=None):
        for _ in range(30):
            row = await self.get(org,run_id)
            expected = row['version']
            before = deepcopy(row)
            operation(row)
            if row == before:
                return row
            committed = await self._commit(row,expected,fence=fence)
            if committed:
                return committed
            await asyncio.sleep(0)
        raise WorkflowConflict('Director state changed concurrently')

    async def claim(self, kind=None, limit=1, lease_seconds=600):
        if kind not in (None,'scene','master') or not 1 <= limit <= 100 or not 1 <= lease_seconds <= 3600:
            raise ValueError('Invalid director queue claim')
        candidates = (deepcopy(list(self.rows.values())) if self.memory else await self._rpc('candidates'))
        claimed = []
        for candidate in sorted(candidates,key=lambda r:r['created_at']):
            if len(claimed)>=limit:
                break
            if candidate.get('superseded_by') or candidate.get('document_fenced') or candidate['state'] in ('BLOCKED','AWAITING_SCRIPT_APPROVAL','AWAITING_HITL'):
                continue
            owned = []
            def apply(row):
                owned.clear()
                if row.get('superseded_by') or row.get('document_fenced') or row['state'] in ('BLOCKED','AWAITING_SCRIPT_APPROVAL','AWAITING_HITL'):
                    return
                task = next((t for t in row['tasks'] if t['status'] in ('pending','leased') and
                    t['lease_until']<=time.time() and (kind is None or t['kind']==kind)),None)
                if task:
                    task['lease_token']=uid()
                    task['lease_until']=time.time()+lease_seconds
                    task['status']='leased'
                    owned.append(task['lease_token'])
            row = await self._mutate(candidate['org_id'],candidate['id'],apply)
            tasks=[t for t in row['tasks'] if t['status']=='leased' and
                t['lease_token'] in owned and t['lease_until']>time.time()]
            claimed.extend(tasks[:1])
        return claimed

    async def submission_started(self, task):
        def apply(row):
            current=fenced(row,task)
            if current['status']=='completed': return
            current['submission_uncertain']=True
            event(row,'DIRECTING_SCENE' if current['kind']=='scene' else 'ASSEMBLING_MASTER',
                'Renderer submission intent persisted',current)
        return await self._mutate(task['org_id'],task['run_id'],apply,fence=task)

    async def submitted(self, task, receipt):
        if not isinstance(receipt,dict) or not receipt.get('task_id'):
            raise ValueError('Renderer receipt requires task_id')
        def apply(row):
            current=fenced(row,task)
            if current['status']=='completed': return
            if current.get('receipt') and current['receipt']!=receipt:
                raise WorkflowConflict('Renderer task receipt changed')
            current['receipt']=deepcopy(receipt)
            current['submission_uncertain']=False
            if current['kind']=='scene':
                scene=next(s for s in row['scenes'] if s['scene_index']==current['scene_index'])
                scene['state']='AWAITING_SCENE_VERIFICATION'
            event(row,'AWAITING_SCENE_VERIFICATION' if current['kind']=='scene' else 'INSPECTING_MASTER',
                  'Renderer accepted task; awaiting automated inspection',current)
        return await self._mutate(task['org_id'],task['run_id'],apply,fence=task)

    async def release(self, task):
        def apply(row):
            current=fenced(row,task)
            if current['status']!='completed':
                current['lease_until']=0
                current['lease_token']=None
                current['status']='pending'
        return await self._mutate(task['org_id'],task['run_id'],apply,fence=task)

    async def renew(self, task, lease_seconds=600):
        def apply(row):
            current=fenced(row,task)
            if current['status']=='completed': return
            current['lease_until']=time.time()+lease_seconds
        return await self._mutate(task['org_id'],task['run_id'],apply,fence=task)

    async def complete(self, task, result, verification):
        return await self._mutate(task['org_id'],task['run_id'],
            lambda row:complete_task(row,fenced(row,task),result,verification),fence=task)

    async def fail(self, task, error, correction=None):
        def apply(row):
            current=fenced(row,task)
            if current['status']!='completed': fail_task(row,current,error,correction)
        return await self._mutate(task['org_id'],task['run_id'],apply,fence=task)

    async def defer(self, task, error, *, uncertain=None):
        """Keep the same attempt and provider key while a submission is uncertain."""
        def apply(row):
            current=fenced(row,task)
            current['last_error']=str(error)
            current['defer_count']=min(current.get('defer_count',0)+1,5)
            if uncertain is not None:
                current['submission_uncertain']=uncertain
            current['lease_until']=time.time()+min(30*2**(current['defer_count']-1),300)
            current['lease_token']=None
            current['status']='pending'
            event(row,'RECONCILING_SUBMISSION' if current['submission_uncertain'] else row['state'],str(error),current)
        return await self._mutate(task['org_id'],task['run_id'],apply,fence=task)

    async def recover(self, org, run_id, *, key=None, expected_revision=None):
        # Recovery expedites a deferred dependency/receipt check; it never rewinds
        # failed attempts, takes another worker's lease, or invents a receipt.
        def apply(row):
            if expected_revision is not None and row['storyboard_revision']!=expected_revision:
                raise WorkflowConflict('Director recovery revision conflict')
            fingerprint=digest(dict(org=org,run_id=run_id,storyboard_revision=expected_revision))
            if key:
                prior=row.setdefault('recovery_receipts',{}).get(key)
                if prior:
                    if prior['fingerprint']!=fingerprint:
                        raise WorkflowConflict('Director recovery idempotency key reused')
                    return
            if row.get('superseded_by') or row.get('document_fenced'):
                raise WorkflowConflict('Recover the current storyboard revision')
            recovered=False
            for task in row['tasks']:
                if task['status']=='pending' and task.get('last_error'):
                    task['lease_until']=0
                    task['defer_count']=0
                    recovered=True
            if recovered:
                event(row,'RECONCILING_SUBMISSION' if any(t.get('submission_uncertain') for t in row['tasks']) else row['state'],
                    'Recovery requested; persisted task will resume')
            if key: row.setdefault('recovery_receipts',{})[key]={'fingerprint':fingerprint}
        return await self._mutate(org,run_id,apply)
