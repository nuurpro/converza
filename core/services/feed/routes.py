"""Authenticated read-only projection, using the existing ownership boundary."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool
from . import InvalidFeedCursor, PendingFeedStore
from .contracts import PendingPage


def create_feed_router(get_repo, authenticate, assert_owner):
    router = APIRouter(prefix='/api/feed', tags=['approval-feed'])

    @router.get('/pending', response_model=PendingPage)
    async def pending(response: Response, org_id: str = Query(min_length=1, max_length=200),
                      limit: int = Query(default=50, ge=1, le=100),
                      cursor: str | None = Query(default=None, min_length=1, max_length=2048),
                      auth=Depends(authenticate)):
        await run_in_threadpool(assert_owner, auth.user_id, org_id)
        response.headers['Cache-Control'] = 'no-store'
        try:
            return await PendingFeedStore(get_repo()).pending(org_id, limit=limit, cursor=cursor)
        except InvalidFeedCursor as exc:
            raise HTTPException(422, str(exc)) from None

    return router
