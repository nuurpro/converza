"""Durable storyboard revisions and edit previews, separate from paid tasks."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid
from starlette.concurrency import run_in_threadpool
from services.workflow.state import WorkflowConflict
from .contracts import Storyboard
from .storyboard import content_hash


def bind_initial_approval(repo,org,campaign,approved_revision):
    """Called under Milo's approval transaction lock; never from a build worker."""
    key=(org,campaign['id'])
    document=getattr(repo,'_director_documents',{}).get(key)
    if document is None:return None
    board=document['storyboard'];approved=campaign['artifact']['video_script']
    if len(approved)!=len(board['scenes']) or any(a['spoken_narration']!=s['narration_chunk'] or a['on_screen_text']!=s['overlay_text']['text'] for a,s in zip(approved,board['scenes'])):
        raise WorkflowConflict('Storyboard changed before script sign-off; refresh and approve the current script')
    updated=deepcopy(document);updated['storyboard']['narration_approved']=True
    updated['campaign_revision']=approved_revision;updated['pending_start']=True
    repo._director_documents[key]=updated
    return board['revision']


def reduce_document(state,action,args):
    state=deepcopy(state or {'storyboard':None,'previews':{},'receipts':{},'pending_start':False})
    if action=='preview':
        if not state['storyboard'] or state['storyboard']['revision']!=args['expected_revision']:
            raise WorkflowConflict('Storyboard changed; refresh the edit preview')
        preview=deepcopy(args['preview']); preview['preview_id']=args['preview_id']
        state['previews'][preview['preview_id']]=preview
        return state,preview
    key=args['key']; fingerprint=content_hash({'action':action,**args})
    cached=state['receipts'].get(key)
    if cached:
        if cached['fingerprint']!=fingerprint: raise WorkflowConflict('Director idempotency key reused')
        return state,cached['result']
    board=state['storyboard']
    if action=='initialize':
        if board: return state,board
        state['storyboard']=Storyboard.model_validate(args['board']).model_dump(mode='json')
        state['campaign_revision']=args['campaign_revision']
    elif action=='replace':
        if board and board['revision']!=args['expected_revision']:raise WorkflowConflict('Storyboard revision conflict')
        replacement=deepcopy(args['board'])
        replacement['revision']=(board['revision']+1) if board else 1
        replacement['narration_approved']=False
        state['storyboard']=Storyboard.model_validate(replacement).model_dump(mode='json')
        state['campaign_revision']=args['campaign_revision']
        state['pending_start']=False
    elif action=='apply':
        if not board or board['revision']!=args['expected_revision']: raise WorkflowConflict('Storyboard revision conflict')
        preview=state['previews'].get(args['preview_id'])
        if not preview or preview['base_revision']!=board['revision']: raise WorkflowConflict('Edit preview expired')
        if preview['unresolved_instructions']: raise WorkflowConflict('Resolve unsupported edit instructions first')
        if preview['scenes']==board['scenes']:raise WorkflowConflict('No storyboard scenes changed')
        narration_changed=len(preview['scenes'])!=len(board['scenes']) or any(
            a['narration_chunk']!=b['narration_chunk'] for a,b in zip(preview['scenes'],board['scenes']))
        state['storyboard']=Storyboard(revision=board['revision']+1,scenes=preview['scenes'],
            narration_approved=board['narration_approved'] and not narration_changed).model_dump(mode='json')
        state['pending_start']=True
    elif action=='approve':
        if not board or board['revision']!=args['expected_revision']: raise WorkflowConflict('Narration revision conflict')
        board['narration_approved']=True; state['pending_start']=True
        if 'campaign_revision' in args:state['campaign_revision']=args['campaign_revision']
    elif action=='started':
        if board and board['revision']==args['expected_revision']: state['pending_start']=False
    else: raise ValueError('Unknown storyboard command')
    result=deepcopy(state['storyboard'])
    state['receipts'][key]={'fingerprint':fingerprint,'result':result}
    return state,result


class DirectorDocuments:
    def __init__(self,repo):
        self.repo=repo; self.memory=not hasattr(repo,'client')
        if self.memory and not hasattr(repo,'_director_documents'): repo._director_documents={}

    async def _rpc(self,action,**args):
        try:
            return (await run_in_threadpool(self.repo.client.rpc('milo_director_documents',{'p_action':action,'p_args':args}).execute)).data
        except Exception as exc:
            if 'workflow_conflict' in str(exc): raise WorkflowConflict('Storyboard ownership or revision conflict') from None
            raise

    async def get(self,org,campaign):
        if not self.memory: return await self._rpc('get',org=org,campaign=campaign)
        return deepcopy(self.repo._director_documents.get((org,campaign)))

    async def pending(self):
        if not self.memory: return await self._rpc('pending')
        return [dict(org_id=o,campaign_id=c,**deepcopy(d)) for (o,c),d in self.repo._director_documents.items() if d.get('pending_start')]

    async def command(self,org,campaign,action,**args):
        if not self.memory:
            # Apply the same reducer to an optimistic snapshot; SQL serializes CAS.
            for _ in range(20):
                previous=await self.get(org,campaign)
                state,result=reduce_document(previous['document'] if previous else None,action,args)
                value=await self._rpc('commit',org=org,campaign=campaign,document=state,
                    expected_version=previous['version'] if previous else -1)
                if value is not None: return result
            raise WorkflowConflict('Storyboard changed concurrently')
        async with self.repo._lock:
            previous=self.repo._director_documents.get((org,campaign))
            document,result=reduce_document(previous,action,args)
            if previous and previous.get('storyboard',{}).get('revision')!=document['storyboard']['revision']:
                from .state import event
                import json
                for run in getattr(self.repo,'_milo_director',{}).values():
                    if run['org_id']==org and run['campaign_id']==campaign and not run.get('superseded_by'):
                        run['document_fenced']=True
                        run['version']+=1
                        event(run,'REVISION_PENDING','Storyboard changed; previous production fenced')
                        await self.repo.insert_agent_run_step(run['id'],org,'milo','REVISION_PENDING','completed',
                            json.dumps(run['progress'][-1],ensure_ascii=False))
                        for draft in self.repo.drafts:
                            if draft['org_id']==org and draft['id']==run.get('draft_id'):
                                draft['director_artifact']={**draft.get('director_artifact',{}),'superseded':True,
                                    'superseded_storyboard_revision':document['storyboard']['revision']}
                                self.repo._event(org,'draft_transition',draft)
            self.repo._director_documents[(org,campaign)]=document
            return deepcopy(result)

    async def document(self,org,campaign):
        row=await self.get(org,campaign)
        return row if self.memory or not row else row['document']

    async def preview(self,org,campaign,expected_revision,preview):
        return await self.command(org,campaign,'preview',expected_revision=expected_revision,preview=preview,preview_id=str(uuid.uuid4()))

    async def handoff(self,job):
        if not self.memory: return await self._rpc('handoff',job=job['id'],token=job['lease_token'],org=job['org_id'])
        from services.milo.store import MiloStore
        async with self.repo._lock:
            store=MiloStore(self.repo); current=store._leased(job)
            store._done(current)
            store.state['campaigns'][job['campaign_id']]['build_status']='running'
