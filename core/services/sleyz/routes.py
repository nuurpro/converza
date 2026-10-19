"""Owner-scoped SLEYZ simulation, channel status and recovery APIs."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from services.workflow import WorkflowConflict
from .channels import instagram_connections
from .store import SleyzStore


class Simulation(BaseModel):
    org_id: str = Field(min_length=1)
    platform: Literal['telegram','instagram']
    customer_id: str = Field(min_length=1,max_length=200)
    customer_handle: str | None = Field(default=None,max_length=200)
    text: str = Field(min_length=1,max_length=16000)


class Revision(BaseModel):
    expected_revision: int = Field(ge=1)


def create_sleyz_router(get_repo, authenticate, assert_owner):
    router = APIRouter(tags=['sleyz'])

    async def scoped(draft_id, auth):
        repo = get_repo()
        draft = await repo.get_draft(draft_id)
        if not draft:
            raise HTTPException(404,'Draft not found')
        await run_in_threadpool(assert_owner,auth.user_id,draft['org_id'])
        if draft.get('agent_slug') != 'sleyz':
            raise HTTPException(422,'SLEYZ draft required')
        return repo,draft

    @router.post('/api/simulate/inbound-dm',status_code=202)
    async def simulate(body: Simulation, idempotency_key: str = Header(min_length=1,max_length=200), auth=Depends(authenticate)):
        await run_in_threadpool(assert_owner,auth.user_id,body.org_id)
        if not body.text.strip():
            raise HTTPException(422,'Message text required')
        envelope = {'org_id':body.org_id,'platform':body.platform,'connection_id':'simulate:'+body.platform,
            'external_message_id':idempotency_key,'customer_id':body.customer_id,
            'customer_handle':body.customer_handle or body.customer_id,'text':body.text,
            'received_at':datetime.now(timezone.utc).isoformat(),'simulated':True}
        try:
            return await SleyzStore(get_repo()).accept(envelope)
        except WorkflowConflict as exc:
            raise HTTPException(409,str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None

    @router.get('/api/sleyz/connections')
    async def status(org_id: str, auth=Depends(authenticate)):
        await run_in_threadpool(assert_owner,auth.user_id,org_id)
        connections = []
        try:
            instagram = instagram_connections()
        except ValueError:
            instagram = {}
        for account,value in instagram.items():
            if str(value['org_id']) == org_id:
                connections.append({'platform':'instagram','connection_id':account,'configured':True})
        repo = get_repo()
        if hasattr(repo,'client'):
            result = await run_in_threadpool(repo.client.table('tg_connections').select('business_connection_id,bot_token').eq('org_id',org_id).limit(1).execute)
            if result.data:
                value = result.data[0]
                connections.append({'platform':'telegram','connection_id':value.get('business_connection_id') or 'direct', 'configured':bool(value.get('bot_token'))})
        return {'connections':connections}

    @router.post('/api/drafts/{draft_id}/refresh',status_code=202)
    async def refresh(draft_id: str, body: Revision, idempotency_key: str = Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo,draft = await scoped(draft_id,auth)
        try:
            return await SleyzStore(repo).refresh(draft['org_id'],draft_id,body.expected_revision,idempotency_key)
        except WorkflowConflict as exc:
            raise HTTPException(409,str(exc)) from None
        except (ValueError,KeyError) as exc:
            raise HTTPException(422,str(exc)) from None

    @router.post('/api/drafts/{draft_id}/retry-learning',status_code=202)
    async def retry_learning(draft_id: str, auth=Depends(authenticate)):
        repo,draft = await scoped(draft_id,auth)
        try:
            await SleyzStore(repo).retry_learning(draft['org_id'],draft_id)
            return await repo.get_draft(draft_id)
        except WorkflowConflict as exc:
            raise HTTPException(409,str(exc)) from None

    return router
