"""Review API and replayable SSE, separate from publisher-only transitions."""
import asyncio
import hmac
import json
import os
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from services.workflow import WorkflowConflict


class Decision(BaseModel):
    expected_revision: int = Field(ge=1)
    final_content: str | None = Field(default=None, max_length=40000)


class PublisherAction(Decision):
    org_id: str
    action: Literal["begin_delivery", "claim_delivery", "delivery_failed", "delivery_ambiguous"] = "begin_delivery"
    receipt: dict[str, Any] | None = None
    error: str | None = None


async def require_publisher(x_publisher_key: str | None = Header(None)):
    expected = os.getenv("PUBLISHER_API_KEY")
    if not expected or not x_publisher_key or not hmac.compare_digest(expected, x_publisher_key):
        raise HTTPException(403, "Publisher credentials required")


def create_workflow_router(get_repo, authenticate, assert_owner):
    router = APIRouter(tags=["workflow"])

    async def scoped_draft(draft_id, auth):
        repo = get_repo()
        draft = await repo.get_draft(draft_id)
        if not draft:
            raise HTTPException(404, "Draft not found")
        await run_in_threadpool(assert_owner, auth.user_id, draft["org_id"])
        return repo, draft

    async def transition(repo, org_id, draft_id, action, body, key, **kwargs):
        try:
            return await repo.transition_draft(org_id, draft_id, action, body.expected_revision, key, **kwargs)
        except WorkflowConflict as error:
            raise HTTPException(409, str(error))
        except KeyError:
            raise HTTPException(404, "Draft not found")
        except ValueError as error:
            raise HTTPException(422, str(error))

    @router.get("/api/drafts")
    async def list_drafts(org_id: str, auth=Depends(authenticate)):
        await run_in_threadpool(assert_owner, auth.user_id, org_id)
        return {"drafts": (await get_repo().snapshot(org_id))["drafts"]}

    @router.get("/api/drafts/{draft_id}")
    async def get_draft(draft_id: str, auth=Depends(authenticate)):
        _, draft = await scoped_draft(draft_id, auth)
        return draft

    @router.post("/api/hitl/{draft_id}/{action}")
    async def decide(draft_id: str, action: Literal["approve", "edit", "reject"], body: Decision,
                     idempotency_key: str = Header(min_length=1, max_length=200), auth=Depends(authenticate)):
        repo, draft = await scoped_draft(draft_id, auth)
        return await transition(repo, draft["org_id"], draft_id, action, body, idempotency_key, edited_content=body.final_content)

    @router.post("/api/drafts/{draft_id}/resolve")
    async def resolve(draft_id: str, body: Decision, idempotency_key: str = Header(min_length=1, max_length=200), auth=Depends(authenticate)):
        repo, draft = await scoped_draft(draft_id, auth)
        if draft.get("agent_slug") != "sleyz" or not draft.get("inbound_text") or not draft.get("prospect_id"):
            raise HTTPException(422, "Only delivered buyer conversations can become objection memory")
        return await transition(repo, draft["org_id"], draft_id, "resolve", body, idempotency_key)

    @router.post("/api/drafts/{draft_id}/retry-generation")
    async def retry(draft_id: str, body: Decision, idempotency_key: str = Header(min_length=1, max_length=200), auth=Depends(authenticate)):
        from lib.switchboard import retry_generation
        repo, draft = await scoped_draft(draft_id, auth)
        try:
            if draft.get('inbound_id'):
                from services.sleyz.store import SleyzStore
                return await SleyzStore(repo).retry_generation(draft['org_id'],draft_id,body.expected_revision,idempotency_key)
            return await retry_generation(org_id=draft["org_id"], draft_id=draft_id, expected_revision=body.expected_revision, idempotency_key=idempotency_key, repo=repo)
        except WorkflowConflict as error:
            raise HTTPException(409, str(error))

    @router.post("/api/drafts/{draft_id}/deliver")
    async def deliver(draft_id: str, body: Decision, idempotency_key: str = Header(min_length=1, max_length=200), auth=Depends(authenticate)):
        from services.sleyz.publication import deliver_sleyz_draft
        repo, draft = await scoped_draft(draft_id, auth)
        try:
            return await deliver_sleyz_draft(repo=repo, org_id=draft["org_id"], draft_id=draft_id, expected_revision=body.expected_revision, idempotency_key=idempotency_key)
        except WorkflowConflict as error:
            raise HTTPException(409, str(error))
        except (ValueError, KeyError) as error:
            raise HTTPException(422, str(error))

    @router.post("/api/internal/drafts/{draft_id}/delivery", dependencies=[Depends(require_publisher)])
    async def delivery(draft_id: str, body: PublisherAction, idempotency_key: str = Header(min_length=1, max_length=200)):
        return await transition(get_repo(), body.org_id, draft_id, body.action, body, idempotency_key, receipt=body.receipt, error=body.error)

    @router.post("/api/internal/drafts/{draft_id}/receipt", dependencies=[Depends(require_publisher)])
    async def receipt(draft_id: str, body: PublisherAction, idempotency_key: str = Header(min_length=1, max_length=200)):
        return await transition(get_repo(), body.org_id, draft_id, "publish", body, idempotency_key, receipt=body.receipt)

    @router.get("/api/dashboard/{org_id}/stats")
    async def stats(org_id: str, auth=Depends(authenticate)):
        await run_in_threadpool(assert_owner, auth.user_id, org_id)
        return {"stats": await get_repo().get_dashboard_stats(org_id)}

    @router.get("/api/squad/stream")
    async def stream(request: Request, org_id: str, cursor: int | None = Query(default=None, ge=0, le=9007199254740991),
                     last_event_id: str | None = Header(default=None), auth=Depends(authenticate)):
        await run_in_threadpool(assert_owner, auth.user_id, org_id)
        if last_event_id:
            try:
                cursor = max(0, int(last_event_id))
            except ValueError:
                raise HTTPException(422, "Invalid Last-Event-ID")
        repo = get_repo()

        def encode(payload, event_id):
            return f"id: {event_id}\ndata: {json.dumps(payload, default=str)}\n\n"

        async def events():
            after = cursor
            snapshot = await repo.snapshot(org_id)
            # A cursor outside the retained range must hydrate a fresh snapshot.
            pending = await repo.read_events(org_id, after or 0) if after is not None else []
            if after is None or after > snapshot["cursor"] or (pending and pending[0]["id"] > after + 1) or (after < snapshot["cursor"] and not pending):
                after = snapshot["cursor"]
                yield encode({"type": "snapshot", "schema_version": 1, **snapshot}, after)
            heartbeat = time.monotonic()
            checked = time.monotonic()
            while not await request.is_disconnected():
                try:
                    if time.monotonic() - checked >= 60:
                        await authenticate(authorization=request.headers.get("authorization"), x_supabase_access_token=request.headers.get("x-supabase-access-token"), access_token=request.query_params.get("access_token"))
                        await run_in_threadpool(assert_owner, auth.user_id, org_id)
                        checked = time.monotonic()
                    rows = await repo.read_events(org_id, after or 0)
                    for event in rows:
                        after = event["id"]
                        yield encode({"schema_version": 1, "event_id": after, "type": event["type"], **event["payload"]}, after)
                    if time.monotonic() - heartbeat >= 15:
                        yield ": heartbeat\n\n"
                        heartbeat = time.monotonic()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    yield "data: {\"type\":\"error\",\"error\":\"Live updates unavailable. Reconnecting.\"}\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control":"no-cache, no-transform", "X-Accel-Buffering":"no"})

    return router
