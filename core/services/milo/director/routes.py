"""Owner-scoped storyboard editing and autonomous production status."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fastapi import Header,HTTPException,Depends
from pydantic import Field,StrictInt
from services.milo.contracts import Contract
from services.milo.store import MiloStore
from services.milo.evidence import load_context
from services.milo.pipeline import validate_brand_compliance,review_compliance
from services.workflow.state import WorkflowConflict
from .documents import DirectorDocuments,reduce_document
from .store import DirectorStore
from .storyboard import interpret_edit,as_campaign,DirectorInferenceUnavailable
from .runtime import enabled,start_document


class Revision(Contract):
    expected_revision: StrictInt = Field(ge=1)


class Directive(Revision):
    directive: str = Field(min_length=1,max_length=8000)


class ApplyEdit(Revision):
    preview_id: str = Field(min_length=1,max_length=200)


class Recovery(Revision):
    run_id: str = Field(min_length=1,max_length=200)


def register(router,scoped,authenticate):
    async def owned(org,cid,auth):
        repo=await scoped(org,auth);campaign=await MiloStore(repo).get_campaign(org,cid)
        if not campaign:raise HTTPException(404,'Campaign not found')
        return repo,campaign

    async def checked(repo,org,campaign,scenes):
        ctx=await load_context(repo,org,MiloStore(repo),since=datetime.now(timezone.utc)-timedelta(days=7))
        candidate=as_campaign(campaign['artifact'],scenes)
        report=validate_brand_compliance(candidate,ctx)
        if report['passed']:report=await review_compliance(candidate,ctx)
        if not report['passed']:raise HTTPException(409,{'message':'Storyboard violates current brand evidence','violations':report['violations']})

    @router.get('/campaigns/{campaign_id}/director')
    async def status(org_id:str,campaign_id:str,auth=Depends(authenticate)):
        repo,_=await owned(org_id,campaign_id,auth)
        doc=await DirectorDocuments(repo).document(org_id,campaign_id)
        runs=await DirectorStore(repo).list_for_campaign(org_id,campaign_id)
        run=next((r for r in runs if not r.get('superseded_by')),None)
        if run:
            run=deepcopy(run);run['status']=run['state'];run['total_scenes']=len(run['scenes'])
            run['error']=(run.get('alert') or {}).get('error') or run.get('error') or next((t['last_error'] for t in reversed(run['tasks']) if t.get('last_error')),None)
            run['inspection']=run.get('inspection_report');run['master_artifact']=run.get('master_result')
            run['attempt']=max((t['attempt'] for t in run['tasks'] if t.get('scene_index')==run.get('scene_index')),default=1)
            run.pop('tasks',None)
            run['scenes']=[{'scene_index':s['scene_index'],'state':s['state'],'specification':s['specification'],
                'verified':bool(s.get('verified'))} for s in run['scenes']]
            run['master_artifact']={k:v for k,v in (run.get('master_artifact') or {}).items() if k in ('video_url','thumbnail_url','artifact_sha256','duration_sec')}
        return {'run':run,'storyboard':doc['storyboard'] if doc else None}

    @router.post('/campaigns/{campaign_id}/director/edits/preview')
    async def preview(org_id:str,campaign_id:str,body:Directive,auth=Depends(authenticate)):
        repo,campaign=await owned(org_id,campaign_id,auth);docs=DirectorDocuments(repo)
        doc=await docs.document(org_id,campaign_id)
        if not enabled() or not doc:raise HTTPException(409,'Director storyboard unavailable')
        if doc['storyboard']['revision']!=body.expected_revision:raise HTTPException(409,'Storyboard revision conflict')
        current=await load_context(repo,org_id,MiloStore(repo),since=datetime.now(timezone.utc)-timedelta(days=7))
        try:proposed=await interpret_edit(doc['storyboard'],body.directive,context=current)
        except DirectorInferenceUnavailable as exc:raise HTTPException(503,str(exc)) from None
        except ValueError as exc:raise HTTPException(422,'The edit could not be parsed into valid scene changes; refine the directive.') from None
        if not proposed['unresolved_instructions']:await checked(repo,org_id,campaign,proposed['scenes'])
        try:return await docs.preview(org_id,campaign_id,body.expected_revision,proposed)
        except WorkflowConflict as exc:raise HTTPException(409,str(exc)) from None

    @router.post('/campaigns/{campaign_id}/director/edits')
    async def apply(org_id:str,campaign_id:str,body:ApplyEdit,idempotency_key:str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo,campaign=await owned(org_id,campaign_id,auth);docs=DirectorDocuments(repo)
        doc=await docs.document(org_id,campaign_id)
        if not enabled() or not doc:raise HTTPException(409,'Director storyboard unavailable')
        if idempotency_key in doc['receipts']:
            try:
                _,cached=reduce_document(doc,'apply',dict(expected_revision=body.expected_revision,preview_id=body.preview_id,key=idempotency_key))
                return {'storyboard':cached}
            except WorkflowConflict as exc:raise HTTPException(409,str(exc)) from None
        proposed=doc['previews'].get(body.preview_id)
        if not proposed:raise HTTPException(404,'Edit preview not found')
        await checked(repo,org_id,campaign,proposed['scenes'])
        try:
            board=await docs.command(org_id,campaign_id,'apply',expected_revision=body.expected_revision,preview_id=body.preview_id,key=idempotency_key)
            # A pending narration branch immediately fences the old run as well.
            await start_document(repo,org_id,campaign_id,await docs.document(org_id,campaign_id))
            return {'storyboard':board}
        except WorkflowConflict as exc:raise HTTPException(409,str(exc)) from None

    @router.post('/campaigns/{campaign_id}/director/storyboard/approve')
    async def approve(org_id:str,campaign_id:str,body:Revision,idempotency_key:str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo,campaign=await owned(org_id,campaign_id,auth);docs=DirectorDocuments(repo)
        doc=await docs.document(org_id,campaign_id)
        if not enabled() or not doc:raise HTTPException(409,'Director storyboard unavailable')
        if idempotency_key in doc['receipts']:
            try:
                _,cached=reduce_document(doc,'approve',dict(expected_revision=body.expected_revision,campaign_revision=campaign['revision'],key=idempotency_key))
                return {'storyboard':cached}
            except WorkflowConflict as exc:raise HTTPException(409,str(exc)) from None
        await checked(repo,org_id,campaign,doc['storyboard']['scenes'])
        try:
            board=await docs.command(org_id,campaign_id,'approve',expected_revision=body.expected_revision,campaign_revision=campaign['revision'],key=idempotency_key)
            await start_document(repo,org_id,campaign_id,await docs.document(org_id,campaign_id))
            return {'storyboard':board}
        except WorkflowConflict as exc:raise HTTPException(409,str(exc)) from None

    @router.post('/campaigns/{campaign_id}/director/recover')
    async def recover(org_id:str,campaign_id:str,body:Recovery,idempotency_key:str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo,_=await owned(org_id,campaign_id,auth);store=DirectorStore(repo)
        try:run=await store.get(org_id,body.run_id)
        except WorkflowConflict:raise HTTPException(404,'Director run not found') from None
        doc=await DirectorDocuments(repo).document(org_id,campaign_id)
        if run['campaign_id']!=campaign_id or not doc or doc['storyboard']['revision']!=body.expected_revision:raise HTTPException(409,'Production revision conflict')
        try:return await store.recover(org_id,body.run_id,key=idempotency_key)
        except WorkflowConflict as exc:raise HTTPException(409,str(exc)) from None
