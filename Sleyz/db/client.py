"""Lazy service-role storage. Never create clients or require secrets on import."""
import logging
import os
import uuid

import httpx
from core.db import get_supabase
from lib.repository import SupabaseRepository

logger = logging.getLogger("converza.sales.db")
SALES_BOT_TOKEN = os.getenv("SALES_BOT_TOKEN", "")


def get_client():
    return get_supabase()


def get_repository():
    return SupabaseRepository(get_client())


def _one(query):
    rows = query.limit(1).execute().data or []
    return rows[0] if rows else None


def _unique_routing_org(query):
    rows = query.limit(2).execute().data or []
    if len(rows) > 1:
        logger.error("sales_routing_ambiguous configure_unique_organization_connection")
        return None
    return rows[0] if rows else None


def get_org_by_sales_token(bot_token):
    if not bot_token:
        return None
    return _unique_routing_org(get_client().table("tg_connections").select("*").eq("bot_token", bot_token))


def get_org_by_business_connection(connection_id):
    if not connection_id:
        return None
    return _unique_routing_org(get_client().table("tg_connections").select("*").eq("business_connection_id", connection_id))


def get_connection_by_org(org_id):
    return _one(get_client().table("tg_connections").select("*").eq("org_id", org_id))


def save_business_connection(org_id, connection_id, enabled):
    # Disconnection removes the routing key; disabled connections cannot ingest.
    return get_client().table("tg_connections").update({"business_connection_id": connection_id if enabled else None}).eq("org_id", org_id).execute().data


def get_prospect(org_id, prospect_id):
    return _one(get_client().table("prospects").select("*").eq("org_id", org_id).eq("id", prospect_id))


def upsert_prospect(org_id, tg_user_id, username, first_name, tg_chat_id, *, business_connection_id=None):
    if not isinstance(tg_user_id, int) or not isinstance(tg_chat_id, int):
        raise ValueError("Telegram sender and chat IDs are required")
    client = get_client()
    values = {"org_id": org_id, "platform": "telegram", "external_id": str(tg_user_id),
              "metadata": {"username": username, "first_name": first_name},
              "tg_chat_id": tg_chat_id, "business_connection_id": business_connection_id}
    rows = client.table("prospects").upsert(values, on_conflict="org_id,platform,external_id").execute().data or []
    if not rows:
        raise RuntimeError("Prospect upsert returned no record")
    prospect = rows[0]
    if not prospect.get("conversation_id"):
        updated = client.table("prospects").update({"conversation_id": str(uuid.uuid4())}).eq("org_id", org_id).eq("id", prospect["id"]).execute().data or []
        if updated:
            prospect = updated[0]
    return prospect


def log_message(org_id, prospect_id, role, content, sent_by):
    if role not in ("user", "assistant", "human_edit") or sent_by not in ("ai", "human", "system"):
        raise ValueError("Unsupported conversation message role")
    prospect = get_prospect(org_id, prospect_id)
    if not prospect:
        raise KeyError("Prospect not found in this organization")
    values = {"org_id": org_id, "prospect_id": prospect_id, "role": role, "content": content,
              "sent_by": sent_by, "conversation_id": prospect.get("conversation_id")}
    return get_client().table("messages").insert(values).execute().data


def get_history(org_id, prospect_id, limit=20):
    rows = get_client().table("messages").select("role,content,created_at").eq("org_id", org_id).eq("prospect_id", prospect_id).order("created_at", desc=True).limit(max(1, min(limit, 50))).execute().data or []
    return [{"role": "user" if row["role"] == "user" else "assistant", "content": row["content"]} for row in reversed(rows)]


async def send_telegram(bot_token, chat_id, text, *, reply_markup=None, business_connection_id=None):
    if not bot_token or not chat_id:
        raise ValueError("Telegram bot token and destination are required")
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if business_connection_id:
        payload["business_connection_id"] = business_connection_id
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload)
    response.raise_for_status()
    result = response.json()
    if result.get("ok") is not True:
        raise RuntimeError("Telegram rejected notification")
    return result
