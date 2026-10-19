"""Review notifications and publication through the shared draft state machine."""
import logging
import os
from starlette.concurrency import run_in_threadpool
# Retain the legacy symbol for callers while dispatching all sales safeguards.
from services.sleyz.publication import deliver_sleyz_draft as deliver_telegram_draft
from Sleyz.db import client as db

logger = logging.getLogger("converza.sales.reporter")


async def report_hitl(org_id, prospect_id, draft_id, tg_chat_id, biz_conn_id, inbound_text, draft):
    # Bots cannot DM each other. Post an owner review card using the manager bot.
    conn = await run_in_threadpool(db.get_connection_by_org, org_id)
    token = os.getenv("MANAGER_BOT_TOKEN")
    if not conn or not conn.get("group_chat_id") or not token:
        logger.warning("sales_review_notification_unconfigured org=%s draft=%s", org_id, draft_id)
        return False
    row = await db.get_repository().get_draft(draft_id)
    if not row or row["org_id"] != org_id or row.get("prospect_id") != prospect_id:
        raise KeyError(draft_id)
    revision = row["revision"]
    keyboard = {"inline_keyboard": [[{"text": "Approve", "callback_data": f"approve:{draft_id}:{revision}"},
                                      {"text": "Edit", "callback_data": f"edit:{draft_id}:{revision}"},
                                      {"text": "Reject", "callback_data": f"reject:{draft_id}:{revision}"}]]}
    text = f"Review customer reply\n\nCustomer said:\n{row['inbound_text']}\n\nDraft:\n{row['draft_content']}"
    await db.send_telegram(token, conn["group_chat_id"], text, reply_markup=keyboard)
    return True


async def report_done(task_type, summary, *, org_id=None):
    if not org_id:
        return False
    conn = await run_in_threadpool(db.get_connection_by_org, org_id)
    token = os.getenv("MANAGER_BOT_TOKEN")
    if not conn or not conn.get("group_chat_id") or not token:
        return False
    await db.send_telegram(token, conn["group_chat_id"], f"{task_type}: {summary}")
    return True


async def send_approved_reply(draft_id, final_content, tg_chat_id, biz_conn_id, org_id, prospect_id, *, expected_revision=None, idempotency_key=None):
    """Legacy args retained; destination and final copy always come from storage."""
    repo = db.get_repository()
    draft = await repo.get_draft(draft_id)
    if not draft or draft["org_id"] != org_id or draft.get("prospect_id") != prospect_id:
        raise KeyError(draft_id)
    if draft["status"] == "PUBLISHED":
        return draft
    result = await deliver_telegram_draft(repo=repo, org_id=org_id, draft_id=draft_id,
        expected_revision=expected_revision if expected_revision is not None else draft["revision"],
        idempotency_key=idempotency_key or f"sales-publish:{draft_id}")
    if result["status"] == "PUBLISHED":
        try:
            await run_in_threadpool(db.log_message, org_id, prospect_id, "assistant", draft.get("final_content") or draft["draft_content"], "ai")
            await report_done("customer_reply", f"Delivered reply for draft {draft_id}.", org_id=org_id)
        except Exception as exc:
            logger.warning("sales_delivery_followup_failed org=%s draft=%s error_type=%s", org_id, draft_id, type(exc).__name__)
    return result
