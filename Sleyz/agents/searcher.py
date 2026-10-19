"""Shared Tier 1 identity, Tier 2 evidence and latest sales conversation turns."""
from starlette.concurrency import run_in_threadpool
from services.memory import MemoryStore
from Sleyz.db import client as db


async def build_context(org_id: str, message: str, *, prospect_id: str) -> dict:
    client = await run_in_threadpool(db.get_client)
    context = await run_in_threadpool(MemoryStore(client).context, org_id, message)
    history = await run_in_threadpool(db.get_history, org_id, prospect_id, limit=20)
    return {**context, "history": history}
