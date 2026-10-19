"""Authenticated Telegram ingress and durable sales draft generation."""
import hmac
import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from Sleyz.agents import closer, ingestor, reporter, searcher
from Sleyz.db import client as db

router = APIRouter()
logger = logging.getLogger("converza.sales.webhook")


async def _process(result):
    org_id, prospect_id, text = result["org_id"], result["prospect_id"], result["text"]
    repo = db.get_repository()
    draft = await repo.create_draft(org_id, "sleyz", text, "", prospect_id=prospect_id)
    key = f"sales-generation:{draft['id']}:{uuid.uuid4()}"
    draft = await repo.transition_draft(org_id, draft["id"], "generation_started", draft["revision"], key + ":start")
    try:
        context = await searcher.build_context(org_id, text, prospect_id=prospect_id)
        copy = await closer.generate(text, context, org_id, prospect_id)
        draft = await repo.transition_draft(org_id, draft["id"], "ready", draft["revision"], key + ":ready", edited_content=copy)
    except Exception as exc:
        draft = await repo.transition_draft(org_id, draft["id"], "generation_failed", draft["revision"], key + ":failed", error=type(exc).__name__)
        logger.warning("sales_generation_failed org=%s draft=%s error_type=%s", org_id, draft["id"], type(exc).__name__)
        return draft
    try:
        await reporter.report_hitl(org_id, prospect_id, draft["id"], result["tg_chat_id"], result.get("biz_conn_id"), text, copy)
    except Exception as exc:
        logger.warning("sales_review_notification_failed org=%s draft=%s error_type=%s", org_id, draft["id"], type(exc).__name__)
    return draft


async def handle_business_connection(bc):
    try:
        org = await run_in_threadpool(db.get_org_by_sales_token, db.SALES_BOT_TOKEN)
        if org is None or bc.get("user", {}).get("id") != org.get("owner_tg_id"):
            logger.warning("sales_business_connection_unrecognized")
            return
        await run_in_threadpool(db.save_business_connection, org["org_id"], bc["id"], bool(bc.get("is_enabled", False)))
    except Exception as exc:
        logger.warning("sales_business_connection_failed error_type=%s", type(exc).__name__)


async def handle_business_message(biz_conn_id, tg_user_id, tg_username, tg_first_name, tg_chat_id, text):
    try:
        result = await ingestor.run(biz_conn_id, tg_user_id, tg_username, tg_first_name, tg_chat_id, text)
        if result:
            await _process(result)
    except Exception as exc:
        logger.warning("sales_ingestion_failed error_type=%s", type(exc).__name__)


async def handle_direct_message(tg_user_id, tg_username, tg_first_name, tg_chat_id, text):
    try:
        result = await ingestor.run_direct(db.SALES_BOT_TOKEN, tg_user_id, tg_username, tg_first_name, tg_chat_id, text)
        if result:
            await _process(result)
    except Exception as exc:
        logger.warning("sales_ingestion_failed error_type=%s", type(exc).__name__)


@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    expected = os.getenv("SALES_WEBHOOK_SECRET")
    received = request.headers.get("x-telegram-bot-api-secret-token")
    if not expected or not received or not hmac.compare_digest(expected.encode(), received.encode()):
        raise HTTPException(403, "Telegram webhook credentials required")
    update = await request.json()
    if "business_connection" in update:
        background_tasks.add_task(handle_business_connection, update["business_connection"])
        return {"ok": True}
    business = "business_message" in update
    msg = update.get("business_message") if business else update.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("text"), str) or not msg["text"].strip():
        return {"ok": True}
    sender, chat = msg.get("from") or {}, msg.get("chat") or {}
    if sender.get("is_bot") or not isinstance(sender.get("id"), int) or not isinstance(chat.get("id"), int) or (not business and chat.get("type") != "private"):
        return {"ok": True}
    args = (sender["id"], sender.get("username"), sender.get("first_name"), chat["id"], msg["text"])
    if business:
        if not msg.get("business_connection_id"):
            return {"ok": True}
        background_tasks.add_task(handle_business_message, msg["business_connection_id"], *args)
    else:
        background_tasks.add_task(handle_direct_message, *args)
    return {"ok": True}
