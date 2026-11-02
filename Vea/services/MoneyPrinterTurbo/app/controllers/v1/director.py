"""Authenticated director submission, reconciliation, and evidence downloads."""
import hmac
import os
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from app.services import director


def authenticate(authorization: str | None = Header(default=None)):
    key = os.getenv('MPT_API_KEY', '').strip()
    if not key: raise HTTPException(503, 'Renderer control authentication is not configured')
    if not hmac.compare_digest((authorization or '').encode(), ('Bearer ' + key).encode()):
        raise HTTPException(401, 'Renderer control authentication required')


router = APIRouter(prefix='/api/v1/director', dependencies=[Depends(authenticate)])


@router.get('/context')
def context(org_id: str = Query(min_length=1), product_id: str | None = None, language: Literal['en', 'ru', 'uz'] = 'en'):
    try:
        return director.rendering_context(org_id, product_id, language)
    except (director.vea.VeaError, OSError, TypeError, ValueError) as exc:
        raise HTTPException(422, {'code': getattr(exc, 'code', 'context_unavailable'), 'message': str(exc)[:1000]}) from exc


def public_receipt(receipt):
    return {k: receipt[k] for k in ('task_id', 'status', 'kind', 'binding', 'result', 'error')}


def submit(kind, payload, background, raw=None):
    try:
        # Retain exactly the caller's canonical specification, including numeric
        # JSON representation, so its approved hash never changes on coercion.
        receipt = director.store().submit(kind, raw if raw is not None else payload.model_dump(mode='json'))
    except director.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if receipt['status'] == 'queued': background.add_task(director.execute, receipt['task_id'])
    return public_receipt(receipt)


@router.post('/scenes', status_code=202)
async def scenes(payload: director.SceneRequest, background: BackgroundTasks, request: Request):
    return submit('scene', payload, background, await request.json())


@router.post('/masters', status_code=202)
async def masters(payload: director.MasterRequest, background: BackgroundTasks, request: Request):
    return submit('master', payload, background, await request.json())


@router.get('/tasks/{task_id}')
def status(task_id: str, background: BackgroundTasks, org_id: str = Query(min_length=1)):
    receipts = director.store(); receipts.recover()
    receipt = receipts.get(task_id, org_id)
    if not receipt: raise HTTPException(404, 'Task not found')
    # Polling reconciles a committed submission whose process died before dispatch.
    if receipt['status'] == 'queued': background.add_task(director.execute, task_id)
    return public_receipt(receipt)


@router.get('/tasks')
def lookup(background: BackgroundTasks, org_id: str = Query(min_length=1), idempotency_key: str = Query(min_length=1)):
    receipts = director.store(); receipts.recover()
    receipt = receipts.lookup(org_id, idempotency_key)
    if not receipt: raise HTTPException(404, 'Task not found')
    if receipt['status'] == 'queued': background.add_task(director.execute, receipt['task_id'])
    return public_receipt(receipt)


@router.get('/tasks/{task_id}/artifacts/{filename}')
def artifact(task_id: str, filename: Literal['final-1.mp4', 'narration.wav', 'background.wav', 'evidence.json'], org_id: str = Query(min_length=1)):
    receipt = director.store().get(task_id, org_id)
    if not receipt or receipt['status'] != 'complete': raise HTTPException(404, 'Artifact not found')
    path = director.artifact_dir(task_id) / filename
    if not path.is_file(): raise HTTPException(404, 'Artifact not found')
    return FileResponse(path)
