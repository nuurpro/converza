"""
Converza Manager — account-manager / chief-of-staff agent.

Handles: client onboarding over private DM, brand passport collection, group
workspace setup, owner Q&A grounded in stats + passport, and group-side
coordination of the Sales bot (HITL cards, reports).
"""

import os
import json
import re
import html
from datetime import datetime, timezone

# The legacy manager can still launch from core/manager without PYTHONPATH.
try:
    from services.llm import complete_text
except ModuleNotFoundError as exc:
    if exc.name != "services":
        raise
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from services.llm import complete_text

from workflow_adapter import decide_and_publish

from db.client import (
    sb,
    SALES_BOT_TOKEN,
    get_org_by_owner,
    get_org_by_group,
    get_passport,
    get_stats,
    create_org,
    update_connection,
    update_passport,
    update_org_name,
    send_telegram,
)

# ── Config ───────────────────────────────────────────────────────────────────

MANAGER_BOT_TOKEN = os.environ.get("MANAGER_BOT_TOKEN", "")
SALES_BOT_USERNAME = os.environ.get("SALES_BOT_USERNAME", "@ConverzaSales_bot")

_PERSONA_PATH = os.path.join(os.path.dirname(__file__), "..", "personas", "manager.md")
with open(_PERSONA_PATH, encoding="utf-8") as _f:
    PERSONA = _f.read()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Huawei ─────────────────────────────────────────────────────────────────────

async def call_groq(system: str, user: str) -> str:
    """Compatibility name retained for existing manager handlers."""
    return await complete_text(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        operation="reasoning", max_tokens=300,
    )


def _build_system_prompt(passport: dict | None, stats: dict) -> str:
    return (
        PERSONA
        + "\n\nCLIENT STATS:\n"
        + json.dumps(stats)
        + "\n\nBRAND PASSPORT:\n"
        + json.dumps(passport or {}, indent=2, default=str)
    )


# ── Onboarding parsers ───────────────────────────────────────────────────────

def _parse_faq(text: str) -> list[dict]:
    """Parse Q:/A: pairs into [{question, answer}, ...] (Sales-bot compatible)."""
    pairs: list[dict] = []
    current_q: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped[:2].upper() == "Q:":
            current_q = stripped[2:].strip()
        elif stripped[:2].upper() == "A:" and current_q is not None:
            pairs.append({"question": current_q, "answer": stripped[2:].strip()})
            current_q = None
    return pairs


def _parse_pricing(text: str) -> list[dict]:
    """Parse TIER:/PRICE:/FEATURES: blocks into [{tier, price, features[]}, ...]."""
    tiers: list[dict] = []
    current: dict = {}
    for line in text.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("TIER:"):
            if current.get("tier"):
                tiers.append(current)
            current = {"tier": stripped.split(":", 1)[1].strip()}
        elif upper.startswith("PRICE:"):
            current["price"] = stripped.split(":", 1)[1].strip()
        elif upper.startswith("FEATURES:"):
            feats = stripped.split(":", 1)[1].strip()
            current["features"] = [f.strip() for f in feats.split(",") if f.strip()]
    if current.get("tier"):
        tiers.append(current)
    return tiers


# ── Private DM (onboarding + owner Q&A) ──────────────────────────────────────

_WELCOME = (
    "Welcome. I'm your AI Chief of Staff at Converza.\n"
    "I'll set up your brand in 4 quick steps.\n\n"
    "Step 1 of 4: What is your brand name?"
)


def _state_prompt(state: str | None) -> str:
    """Re-prompt text for the current onboarding step."""
    if state == "collecting_brand_name":
        return "Step 1 of 4: What is your brand name?"
    if state == "collecting_offer":
        return "Step 2 of 4: What do you sell? One sentence — your core offer."
    if state == "collecting_faq":
        return (
            "Step 3 of 4: Send me your top 5 FAQs.\n"
            "Use this format exactly:\n\n"
            "Q: your question\n"
            "A: your answer\n\n"
            "Repeat for each one. Send all 5 in one message."
        )
    if state == "collecting_pricing":
        return (
            "Step 4 of 4: Send me your pricing.\n"
            "Use this format:\n\n"
            "TIER: name\n"
            "PRICE: amount\n"
            "FEATURES: feature1, feature2, feature3\n\n"
            "Repeat for each pricing tier."
        )
    return "Setup is complete. Send /status for a report."


async def handle_private_dm(owner_tg_id: int, text: str) -> str:
    text = text or ""
    stripped = text.strip()
    conn = get_org_by_owner(owner_tg_id)

    # ── Slash commands: never treat them as onboarding answers ───────────────
    if stripped.startswith("/"):
        # Brand-new owner → start them (same as the new-client flow).
        if conn is None:
            create_org(owner_tg_id)
            return _WELCOME
        state = conn.get("onboarding_state")
        if state != "ready":
            if stripped == "/start":
                return _state_prompt(state)
            return "Please complete setup first. " + _state_prompt(state)
        # state == "ready"
        if stripped == "/status":
            passport = get_passport(conn["org_id"]) or {}
            stats = get_stats(conn["org_id"])
            brand_name = passport.get("brand_name", "")
            core_offer = passport.get("core_offer", "")
            return (
                f"Status Report — {brand_name}\n\n"
                f"Leads: {stats['prospects']}\n"
                f"Messages logged: {stats['messages']}\n"
                f"Drafts pending approval: {stats['pending_drafts']}\n"
                f"Drafts approved: {stats['approved_drafts']}\n\n"
                f"Brand: {brand_name}\n"
                f"Offer: {core_offer}"
            )
        # Any other slash command while ready → pass through to owner Q&A below.

    # New client (non-slash first message).
    if conn is None:
        create_org(owner_tg_id)
        return _WELCOME

    org_id = conn["org_id"]
    state = conn.get("onboarding_state")

    if state == "collecting_brand_name":
        update_passport(org_id, brand_name=text)
        update_org_name(org_id, text)
        update_connection(org_id, onboarding_state="collecting_offer")
        return (
            f"Got it — <b>{text}</b>.\n\n"
            "Step 2 of 4: What do you sell? \n"
            "One sentence — your core offer."
        )

    if state == "collecting_offer":
        update_passport(org_id, core_offer=text)
        update_connection(org_id, onboarding_state="collecting_faq")
        return (
            "Noted.\n\n"
            "Step 3 of 4: Send me your top 5 FAQs.\n"
            "Use this format exactly:\n\n"
            "Q: your question\n"
            "A: your answer\n\n"
            "Repeat for each one. Send all 5 in one message."
        )

    if state == "collecting_faq":
        parsed = _parse_faq(text)
        if len(parsed) < 1:
            return (
                "I couldn't parse that. Please use exactly:\n"
                "Q: question\n"
                "A: answer"
            )
        update_passport(org_id, faq=parsed)
        update_connection(org_id, onboarding_state="collecting_pricing")
        return (
            f"Saved {len(parsed)} FAQs.\n\n"
            "Step 4 of 4: Send me your pricing.\n"
            "Use this format:\n\n"
            "TIER: name\n"
            "PRICE: amount\n"
            "FEATURES: feature1, feature2, feature3\n\n"
            "Repeat for each pricing tier."
        )

    if state == "collecting_pricing":
        parsed = _parse_pricing(text)
        if len(parsed) < 1:
            return (
                "I couldn't parse that. Please use this format:\n\n"
                "TIER: name\n"
                "PRICE: amount\n"
                "FEATURES: feature1, feature2, feature3"
            )
        update_passport(org_id, pricing=parsed)
        update_connection(org_id, onboarding_state="ready")
        return (
            "Brand Passport complete.\n\n"
            "Now do this:\n"
            "1. Create a new Telegram group\n"
            f"2. Add <b>{SALES_BOT_USERNAME}</b> as admin\n"
            "3. Add me (<b>@ConverzaApp_bot</b>) as admin\n"
            "4. Send any message in the group\n\n"
            "I will connect everything automatically."
        )

    # state == "ready" (or anything else) → owner Q&A grounded in stats + passport.
    passport = get_passport(org_id)
    stats = get_stats(org_id)
    system = _build_system_prompt(passport, stats)
    return await call_groq(system, text)


# ── Group setup ──────────────────────────────────────────────────────────────

async def handle_group_setup(
    group_chat_id: int,
    owner_tg_id: int,
    bot_token: str | None = None,
) -> str:
    conn = get_org_by_owner(owner_tg_id)
    if conn is None:
        return "Send me a DM first to set up your brand."

    org_id = conn["org_id"]
    updates = {"group_chat_id": group_chat_id}
    if not conn.get("bot_token"):
        updates["bot_token"] = SALES_BOT_TOKEN
    update_connection(org_id, **updates)

    return (
        "Group workspace connected.\n\n"
        "<b>Your team is ready:</b>\n"
        f"{SALES_BOT_USERNAME} — handles customer DMs\n"
        "@ConverzaApp_bot — your chief of staff\n\n"
        "Tag me anytime to check on leads or request tasks.\n\n"
        f"{SALES_BOT_USERNAME} INIT:{org_id}"
    )


# ── Group messages (owner Q&A + Sales-bot reports) ───────────────────────────

async def _post_hitl_card(conn: dict, text: str) -> None:
    """Hydrate a review card, accepting both legacy report encodings."""
    match = re.search(r'(?:draft_id:\s*|REPORT:HITL\s+)([0-9a-fA-F-]{36})', text)
    if not match:
        return
    draft_id = match.group(1)
    result = sb.table('drafts').select('*').eq('id', draft_id).eq('org_id',conn['org_id']).limit(1).execute()
    if not result.data or result.data[0]['status'] != 'AWAITING_HITL':
        return
    draft = result.data[0]
    revision = draft['revision']
    card = 'Review this draft before sending:\n\n' + html.escape(draft['draft_content'])
    reply_markup = {'inline_keyboard':[[
        {'text':'Approve','callback_data':f'approve:{draft_id}:{revision}'},
        {'text':'Edit','callback_data':f'edit:{draft_id}:{revision}'},
        {'text':'Reject','callback_data':f'reject:{draft_id}:{revision}'}]]}
    await send_telegram(MANAGER_BOT_TOKEN, conn['group_chat_id'], card, reply_markup)


def _format_done(text: str) -> str:
    """REPORT:DONE {task_type} {summary} → owner-facing summary line."""
    parts = text.split(maxsplit=2)
    summary = parts[2] if len(parts) > 2 else ""
    return summary


async def _handle_edit_reply(conn: dict, text: str) -> str:
    """The third field is a draft revision; destination comes from the prospect."""
    parts = text.split(':', 3)
    if len(parts) != 4:
        return 'Use: EDIT:{draft_id}:{revision}: your message'
    try:
        draft_id, revision, new_msg = parts[1].strip(), int(parts[2].strip()), parts[3].strip()
        result = await decide_and_publish(client=sb, conn=conn, draft_id=draft_id, action='edit',
            revision=revision, key=f'tg-edit:{draft_id}:{revision}', content=new_msg)
    except (ValueError, KeyError) as exc:
        return str(exc)
    if result['status'] == 'PUBLISHED':
        await send_telegram(MANAGER_BOT_TOKEN,conn['group_chat_id'],'Reply delivered. Mark resolved when the buyer issue is resolved.',
            {'inline_keyboard':[[{'text':'Mark resolved','callback_data':f"resolve:{draft_id}:{result['revision']}"}]]})
        return 'Edited draft delivered to prospect.'
    return f"Edit saved. Delivery: {result.get('delivery_status', 'idle')}."


async def handle_group_message(
    group_chat_id: int,
    from_tg_id: int,
    text: str,
) -> str | None:
    conn = get_org_by_group(group_chat_id)
    if conn is None:
        return None

    text = text or ""
    is_owner = from_tg_id == conn.get("owner_tg_id")

    # Owner asking the manager directly.
    if is_owner and ("@ConverzaApp_bot" in text or text.strip().startswith("?")):
        org_id = conn["org_id"]
        passport = get_passport(org_id)
        stats = get_stats(org_id)
        system = _build_system_prompt(passport, stats)
        return await call_groq(system, text)

    # Owner replying to an edit prompt (completes the HITL edit loop).
    if is_owner and text.strip().upper().startswith("EDIT:"):
        return await _handle_edit_reply(conn, text)

    # Reports from the Sales bot.
    if text.startswith("REPORT:HITL"):
        await _post_hitl_card(conn, text)
        return None
    if text.startswith("REPORT:DONE"):
        return _format_done(text)

    # Non-owner chatter / unrecognized → ignore.
    return None
