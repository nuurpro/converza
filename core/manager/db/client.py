"""
Supabase access layer for the Converza Manager bot.

Exports the service-role client `sb` plus thin query/update helpers and the
two Telegram HTTP helpers used across the app.
"""

import os
from datetime import datetime, timezone

import httpx
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY: str = os.environ["SUPABASE_SERVICE_KEY"]
SALES_BOT_TOKEN: str = os.environ.get("SALES_BOT_TOKEN", "")

# Service role client — bypasses RLS, backend use only. Never expose this key.
sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Lookups ──────────────────────────────────────────────────────────────────

def get_org_by_owner(owner_tg_id: int) -> dict | None:
    result = (
        sb.table("tg_connections")
        .select("*")
        .eq("owner_tg_id", owner_tg_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_org_by_group(group_chat_id: int) -> dict | None:
    result = (
        sb.table("tg_connections")
        .select("*")
        .eq("group_chat_id", group_chat_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_org_by_token(bot_token: str) -> dict | None:
    result = (
        sb.table("tg_connections")
        .select("*")
        .eq("bot_token", bot_token)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_connection_by_org(org_id: str) -> dict | None:
    result = (
        sb.table("tg_connections")
        .select("*")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# ── Org / connection / passport mutations ────────────────────────────────────

def create_org(owner_tg_id: int) -> dict:
    """Create a fresh org with an empty passport and a connection in onboarding."""
    org = (
        sb.table("orgs")
        .insert({"name": "New Client", "created_at": _now()})
        .execute()
    )
    org_id = org.data[0]["id"]

    conn = (
        sb.table("tg_connections")
        .insert(
            {
                "org_id": org_id,
                "owner_tg_id": owner_tg_id,
                "onboarding_state": "collecting_brand_name",
                "bot_token": SALES_BOT_TOKEN,
            }
        )
        .execute()
    )

    sb.table("brand_passports").insert({"org_id": org_id, "brand_name": ""}).execute()

    return conn.data[0]


def update_connection(org_id: str, **kwargs) -> None:
    if not kwargs:
        return
    sb.table("tg_connections").update(kwargs).eq("org_id", org_id).execute()


def update_passport(org_id: str, **kwargs) -> None:
    patch = {**kwargs, "updated_at": _now()}
    sb.table("brand_passports").update(patch).eq("org_id", org_id).execute()


def update_org_name(org_id: str, name: str) -> None:
    sb.table("orgs").update({"name": name}).eq("id", org_id).execute()


def get_passport(org_id: str) -> dict | None:
    result = (
        sb.table("brand_passports")
        .select("*")
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_stats(org_id: str) -> dict:
    """Four count queries scoped to the org."""
    prospects = (
        sb.table("prospects").select("id", count="exact").eq("org_id", org_id).execute()
    )
    messages = (
        sb.table("messages").select("id", count="exact").eq("org_id", org_id).execute()
    )
    pending = (
        sb.table("drafts")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .eq("status", "AWAITING_HITL")
        .execute()
    )
    approved = (
        sb.table("drafts")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .in_("status", ["APPROVED", "EDITED", "PUBLISHED"])
        .execute()
    )
    return {
        "prospects": prospects.count or 0,
        "messages": messages.count or 0,
        "pending_drafts": pending.count or 0,
        "approved_drafts": approved.count or 0,
    }


# ── Telegram HTTP helpers ────────────────────────────────────────────────────

async def send_telegram(
    bot_token: str,
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
) -> dict:
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
        )
    resp.raise_for_status()
    result = resp.json()
    if result.get("ok") is not True:
        raise ValueError("Telegram rejected sendMessage")
    return result


async def answer_callback(
    bot_token: str,
    callback_query_id: str,
    text: str,
) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )
