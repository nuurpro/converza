"""Receive buyer messages only through the organization's configured connection."""
from starlette.concurrency import run_in_threadpool
from Sleyz.db import client as db


async def _ingest(org, tg_user_id, tg_username, tg_first_name, tg_chat_id, text, biz_conn_id):
    org_id = org["org_id"]
    prospect = await run_in_threadpool(db.upsert_prospect, org_id, tg_user_id, tg_username, tg_first_name, tg_chat_id, business_connection_id=biz_conn_id)
    await run_in_threadpool(db.log_message, org_id, prospect["id"], "user", text, "human")
    return {"org_id": org_id, "prospect_id": prospect["id"], "tg_chat_id": tg_chat_id, "text": text, "biz_conn_id": biz_conn_id}


async def run(biz_conn_id, tg_user_id, tg_username, tg_first_name, tg_chat_id, text):
    org = await run_in_threadpool(db.get_org_by_business_connection, biz_conn_id)
    if org is None:
        return None
    return await _ingest(org, tg_user_id, tg_username, tg_first_name, tg_chat_id, text, biz_conn_id)


async def run_direct(bot_token, tg_user_id, tg_username, tg_first_name, tg_chat_id, text):
    org = await run_in_threadpool(db.get_org_by_sales_token, bot_token)
    if org is None:
        return None
    return await _ingest(org, tg_user_id, tg_username, tg_first_name, tg_chat_id, text, None)
