"""Authenticated Milo commands. Client approval never supplies compliance results."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import Field, StrictInt
from starlette.concurrency import run_in_threadpool

from services.workflow.state import WorkflowConflict
from .contracts import BrandConfig, Contract, MiloSettings, VideoScene
from .evidence import get_top_buyer_objections, load_context, save_brand
from .pipeline import review_compliance, validate_brand_compliance
from .store import MiloStore


class CampaignRequest(Contract):
    prompt: str = Field(default='', max_length=8000)
    language: Literal['en','ru','uz'] | None = None


class ScriptDecision(Contract):
    expected_revision: StrictInt = Field(ge=1)
    video_script: list[VideoScene] | None = Field(default=None, min_length=1, max_length=12)


class Reconcile(Contract):
    task_id: str = Field(min_length=1,max_length=200,pattern=r'^[A-Za-z0-9_-]+$')


def create_milo_router(get_repo, authenticate, assert_owner):
    router=APIRouter(prefix='/api/milo/{org_id}',tags=['milo'])

    async def scoped(org_id, auth):
        await run_in_threadpool(assert_owner,auth.user_id,org_id)
        return get_repo()

    async def context(repo,org_id):
        store=MiloStore(repo)
        settings=await store.settings(org_id)
        return await load_context(repo,org_id,store,since=datetime.now(timezone.utc)-timedelta(days=settings['window_days']))

    async def invoke(operation):
        try:
            return await operation
        except WorkflowConflict as exc:
            raise HTTPException(409,str(exc)) from None
        except KeyError:
            raise HTTPException(404,'Milo record not found') from None
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None

    @router.get('/campaigns')
    async def campaigns(org_id: str,auth=Depends(authenticate)):
        repo=await scoped(org_id,auth)
        return {'campaigns':await MiloStore(repo).list_campaigns(org_id)}

    @router.post('/campaigns',status_code=202)
    async def generate(org_id: str,body: CampaignRequest,idempotency_key: str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo=await scoped(org_id,auth)
        return await invoke(MiloStore(repo).enqueue(org_id,'manual',prompt=body.prompt,language=body.language,key='manual:'+idempotency_key))

    @router.get('/campaigns/{campaign_id}')
    async def campaign(org_id: str,campaign_id: str,auth=Depends(authenticate)):
        repo=await scoped(org_id,auth)
        row=await MiloStore(repo).get_campaign(org_id,campaign_id)
        if not row: raise HTTPException(404,'Campaign not found')
        return row

    @router.post('/campaigns/{campaign_id}/script/{action}')
    async def decide(org_id: str,campaign_id: str,action: Literal['edit','approve','reject'],body: ScriptDecision,
                     idempotency_key: str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo=await scoped(org_id,auth); store=MiloStore(repo)
        row=await store.get_campaign(org_id,campaign_id)
        if not row: raise HTTPException(404,'Campaign not found')
        script=[scene.model_dump(mode='json') for scene in body.video_script] if body.video_script else None
        if action=='edit' and script is None: raise HTTPException(422,'An edited video script is required')
        if action!='edit' and script is not None: raise HTTPException(422,'Save script edits separately before approval')
        checks=None
        # Decisions already committed must replay without another paid review.
        # Store idempotency validates original client arguments, including revision.
        if row['revision']==body.expected_revision and action!='reject':
            if not row.get('artifact'): raise HTTPException(409,'Campaign has no reviewable artifact')
            candidate=deepcopy(row['artifact'])
            if script is not None: candidate['video_script']=script
            current=await context(repo,org_id)
            checks=validate_brand_compliance(candidate,current)
            if checks['passed']:
                checks=await review_compliance(candidate,current)
            if action=='approve' and not checks['passed']:
                raise HTTPException(409,{'message':'Campaign needs revalidation or new evidence.','violations':checks['violations']})
        return await invoke(store.decide_script(org_id,campaign_id,action,body.expected_revision,idempotency_key,script=script,compliance=checks))

    @router.get('/settings')
    async def settings(org_id: str,auth=Depends(authenticate)):
        return await MiloStore(await scoped(org_id,auth)).settings(org_id)

    @router.put('/settings')
    async def update_settings(org_id: str,body: dict,auth=Depends(authenticate)):
        repo=await scoped(org_id,auth); store=MiloStore(repo)
        try:
            values=MiloSettings.model_validate({**await store.settings(org_id),**body}).model_dump(mode='json')
        except (ValueError, KeyError) as exc:
            raise HTTPException(422,'Invalid Milo settings or timezone') from None
        return await invoke(store.save_settings(org_id,values))

    @router.get('/brand')
    async def brand(org_id: str,auth=Depends(authenticate)):
        repo=await scoped(org_id,auth)
        passport=await repo.get_brand_passport(org_id)
        return BrandConfig.model_validate({k:passport[k] for k in BrandConfig.model_fields if passport.get(k) is not None}).model_dump(mode='json')

    @router.put('/brand')
    async def update_brand(org_id: str,body: BrandConfig,auth=Depends(authenticate)):
        return await invoke(save_brand(await scoped(org_id,auth),org_id,body.model_dump(mode='json'),auth.user_id))

    @router.get('/proof-sources')
    async def proof_sources(org_id: str,auth=Depends(authenticate)):
        current=await context(await scoped(org_id,auth),org_id)
        return {'sources':[{k:r.get(k) for k in ('id','revision','kind','title','content')} |
                           ({'product_id':r['external_id']} if r.get('kind')=='product' else {})
                for r in current['sources'] if r.get('org_id')==org_id and r.get('kind') in ('product','faq','manual') and not r.get('deleted_at') and not r.get('forgotten_at')]}

    @router.get('/objections')
    async def objections(org_id: str,time_window: int | None=Query(default=None,ge=1,le=365),auth=Depends(authenticate)):
        from .tools import MiloTools
        repo=await scoped(org_id,auth)
        window=time_window or (await MiloStore(repo).settings(org_id))['window_days']
        return {'objections':await MiloTools(repo,org_id).get_top_buyer_objections(timedelta(days=window))}

    @router.get('/jobs')
    async def jobs(org_id: str,auth=Depends(authenticate)):
        return {'jobs':await MiloStore(await scoped(org_id,auth)).jobs(org_id)}

    @router.post('/jobs/{job_id}/retry',status_code=202)
    async def retry(org_id: str,job_id: str,idempotency_key: str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        return await invoke(MiloStore(await scoped(org_id,auth)).retry(org_id,job_id,key=idempotency_key))

    @router.post('/jobs/{job_id}/reconcile',status_code=202)
    async def reconcile(org_id: str,job_id: str,body: Reconcile,idempotency_key: str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        # Operator supplies the ORIGINAL provider task receipt, never permission
        # to create a second paid task. Workers resume polling this persisted ID.
        repo=await scoped(org_id,auth); store=MiloStore(repo)
        cached=await invoke(store.replay_reconcile(org_id,job_id,body.task_id,idempotency_key))
        if cached is not None: return cached
        job=next((row for row in await store.jobs(org_id) if row['id']==job_id and row['kind']=='build'),None)
        if not job: raise HTTPException(404,'Build job not found')
        from .video import validate_provider_receipt
        try:
            await validate_provider_receipt(job,body.task_id)
        except Exception:
            raise HTTPException(422,'Provider receipt is unavailable or does not match this organization, job, and approved script.') from None
        return await invoke(store.reconcile_build(org_id,job_id,body.task_id,key=idempotency_key))

    return router
