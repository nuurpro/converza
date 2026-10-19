"""
Single Telegram webhook for the Manager bot.

Always returns {"ok": True} synchronously; all real work runs in background
tasks wrapped in try/except. Every outbound Telegram send goes through
db.client.send_telegram.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, BackgroundTasks

from db.client import (
    sb,
    get_org_by_group,
    get_org_by_owner,
    get_connection_by_org,
    send_telegram,
    answer_callback,
)
from agents import manager
from agents.manager import MANAGER_BOT_TOKEN
from workflow_adapter import decide_and_publish
from services.workflow.state import WorkflowConflict

router = APIRouter()
logger = logging.getLogger("converza.manager.webhook")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Background workers ───────────────────────────────────────────────────────

async def _process_private(from_id: int, text: str, chat_id: int) -> None:
    try:
        reply = await manager.handle_private_dm(from_id, text)
        if reply:
            await send_telegram(MANAGER_BOT_TOKEN, chat_id, reply)
    except Exception:
        logger.exception("private DM handling failed")


async def _process_group(group_chat_id: int, from_id: int, text: str) -> None:
    try:
        conn = get_org_by_group(group_chat_id)

        if conn is None:
            # Not yet connected — only act if the sender is a known owner.
            owner_conn = get_org_by_owner(from_id)
            if owner_conn:
                reply = await manager.handle_group_setup(
                    group_chat_id, from_id, owner_conn.get("bot_token")
                )
                if reply:
                    await send_telegram(MANAGER_BOT_TOKEN, group_chat_id, reply)
            return

        reply = await manager.handle_group_message(group_chat_id, from_id, text)
        if reply is not None:
            await send_telegram(MANAGER_BOT_TOKEN, group_chat_id, reply)
    except Exception:
        logger.exception("group message handling failed")


async def _process_callback(callback: dict) -> None:
    cb_id = callback.get('id')
    try:
        data = callback.get('data') or ''
        group_chat_id = ((callback.get('message') or {}).get('chat') or {}).get('id')
        conn = get_org_by_group(group_chat_id) if group_chat_id is not None else None
        if not conn or (callback.get('from') or {}).get('id') != conn.get('owner_tg_id'):
            await answer_callback(MANAGER_BOT_TOKEN, cb_id, 'Only the workspace owner can decide this draft.')
            return
        parts = data.split(':')
        if len(parts) != 3 or parts[0] not in ('approve','edit','reject','retry','resolve'):
            await answer_callback(MANAGER_BOT_TOKEN, cb_id, 'Refresh this review card.')
            return
        action, draft_id, revision_text = parts
        revision = int(revision_text)
        draft = (sb.table('drafts').select('*').eq('id', draft_id).eq('org_id', conn['org_id']).limit(1).execute().data or [None])[0]
        if not draft:
            await answer_callback(MANAGER_BOT_TOKEN, cb_id, 'Draft not found in this workspace.')
            return
        if action == 'edit':
            if draft['revision'] != revision or draft['status'] != 'AWAITING_HITL':
                raise WorkflowConflict('Draft changed; refresh the review card')
            await answer_callback(MANAGER_BOT_TOKEN, cb_id, f'Reply: EDIT:{draft_id}:{revision}: your message')
            return
        result = await decide_and_publish(client=sb, conn=conn, draft_id=draft_id,
            action=action, revision=revision, key=f'tg:{cb_id}')
        status = result['status']
        await answer_callback(MANAGER_BOT_TOKEN, cb_id, 'Saved: ' + status)
        markup = None
        if status == 'PUBLISHED' and not result.get('resolved_at'):
            markup = {'inline_keyboard':[[{'text':'Mark resolved','callback_data':f"resolve:{draft_id}:{result['revision']}"}]]}
        elif result.get('delivery_status') == 'failed':
            markup = {'inline_keyboard':[[{'text':'Retry delivery','callback_data':f"retry:{draft_id}:{result['revision']}"}]]}
        outcome = 'Delivery needs reconciliation.' if result.get('delivery_status') == 'ambiguous' else f'Draft {status}.'
        await send_telegram(MANAGER_BOT_TOKEN, group_chat_id, outcome, markup)
    except (ValueError, KeyError) as exc:
        await answer_callback(MANAGER_BOT_TOKEN, cb_id, str(exc)[:180])
    except Exception:
        logger.exception('callback handling failed')
        await answer_callback(MANAGER_BOT_TOKEN, cb_id, 'Action failed. Refresh the draft before retrying.')


@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    update = await request.json()

    callback = update.get("callback_query")
    if callback:
        background_tasks.add_task(_process_callback, callback)
        return {"ok": True}

    message = update.get("message")
    if message:
        chat = message.get("chat") or {}
        chat_type = chat.get("type")
        chat_id = chat.get("id")
        from_id = (message.get("from") or {}).get("id")
        text = message.get("text") or ""

        if chat_type == "private":
            background_tasks.add_task(_process_private, from_id, text, chat_id)
        elif chat_type in ("group", "supergroup"):
            background_tasks.add_task(_process_group, chat_id, from_id, text)

        return {"ok": True}

    return {"ok": True}
