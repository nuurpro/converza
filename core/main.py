import json
import asyncio
import os
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from db import get_supabase
from lib.context_assembler import VALID_AGENTS
from lib.repository import SupabaseRepository
from lib.switchboard import (
    handle_direct_agent_message,
    handle_squad_owner_message,
    resolve_hitl,
)

load_dotenv()

class AgentMessageRequest(BaseModel):
    org_id: str
    text: str


class SquadMessageRequest(BaseModel):
    org_id: str
    text: str


class HitlEditRequest(BaseModel):
    final_content: str | None = None


class OnboardingSaveRequest(BaseModel):
    owner_user_id: str
    org_id: str | None = None
    answers: dict[str, Any]


class OnboardingOwnerRequest(BaseModel):
    owner_user_id: str
    org_id: str | None = None


class AuthContext(BaseModel):
    user_id: str


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Converza Co-Pilot", version="0.1.0")
from services.llm.routes import router as llm_service_router
app.include_router(llm_service_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_switchboard_repo() -> SupabaseRepository:
    return SupabaseRepository(get_supabase())


def get_memory_store():
    from services.memory import MemoryStore
    return MemoryStore(get_supabase())


def get_default_org_id() -> str:
    return os.getenv("DEFAULT_ORG_ID") or os.getenv("NEXT_PUBLIC_DEFAULT_ORG_ID") or "00000000-0000-0000-0000-000000000001"


def get_backend_api_key() -> str:
    key = os.getenv("BACKEND_API_KEY")
    if not key:
        raise RuntimeError("BACKEND_API_KEY must be set in .env")
    return key


async def require_api_key(authorization: str | None = Header(None)) -> None:
    expected = f"Bearer {get_backend_api_key()}"
    if not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _normalize_bearer_token(token: str | None) -> str | None:
    if not token:
        return None
    token = token.strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def _get_user_id_from_supabase_token(token: str) -> str:
    result = get_supabase().auth.get_user(token)
    user = getattr(result, "user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise ValueError("Supabase session token did not resolve to a user")
    return str(user_id)


async def require_authenticated_user(
    authorization: str | None = Header(None),
    x_supabase_access_token: str | None = Header(None),
    access_token: str | None = Query(None),
) -> AuthContext:
    await require_api_key(authorization)
    token = _normalize_bearer_token(x_supabase_access_token) or _normalize_bearer_token(access_token)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Supabase session")
    try:
        return AuthContext(user_id=_get_user_id_from_supabase_token(token))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Supabase session")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "Converza Co-Pilot"}


def _fetch_brand_passport(brand_id: str) -> dict:
    """Fetch Brand Passport from Supabase by ID."""
    sb = get_supabase()
    result = sb.table("brand_passports").select("*").eq("id", brand_id).single().execute()
    return result.data


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_missing_onboarding_migration(error: Exception) -> bool:
    message = str(error)
    return "brand_passports.owner_user_id" in message or "42703" in message


def _raise_onboarding_migration_error() -> None:
    raise HTTPException(
        status_code=503,
        detail="Onboarding database migration is pending. Run migrations/003_onboarding_paywall.sql in Supabase, then refresh.",
    )


def _get_passport_by_org(org_id: str) -> dict[str, Any] | None:
    result = (
        get_supabase()
        .table("brand_passports")
        .select("id,org_id,owner_user_id")
        .eq("org_id", org_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _assert_user_owns_org(user_id: str, org_id: str) -> None:
    try:
        passport = _get_passport_by_org(org_id)
    except Exception as e:
        if _is_missing_onboarding_migration(e):
            _raise_onboarding_migration_error()
        raise
    if not passport:
        raise HTTPException(status_code=403, detail="Org is not linked to this user")
    if str(passport.get("owner_user_id")) != user_id:
        raise HTTPException(status_code=403, detail="Org does not belong to this user")


from lib.memory_routes import create_memory_router

app.include_router(create_memory_router(
    lambda: get_memory_store(), require_authenticated_user,
    lambda user_id, org_id: _assert_user_owns_org(user_id, org_id),
))


def _assert_onboarding_owner(auth: AuthContext, owner_user_id: str) -> None:
    if owner_user_id != auth.user_id:
        raise HTTPException(status_code=403, detail="Cannot access onboarding for another user")


def _assert_org_not_owned_by_other(user_id: str, org_id: str) -> None:
    try:
        passport = _get_passport_by_org(org_id)
    except Exception as e:
        if _is_missing_onboarding_migration(e):
            _raise_onboarding_migration_error()
        raise
    if passport and str(passport.get("owner_user_id")) != user_id:
        raise HTTPException(status_code=403, detail="Org is already linked to another user")


def _onboarding_payload(owner_user_id: str, org_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    tones = answers.get("brand_tone") or []
    colors = answers.get("brand_colors") or []
    channels = answers.get("channels_requested") or []
    return {
        "owner_user_id": owner_user_id,
        "org_id": org_id,
        "onboarding_answers": answers,
        "brand_name": answers.get("business_name") or "Untitled brand",
        "industry": answers.get("industry"),
        "core_offer": answers.get("core_offer"),
        "target_audience": answers.get("ideal_customer"),
        "target_location": answers.get("customer_location"),
        "tone": ", ".join(tones) if isinstance(tones, list) else tones,
        "hex_colors": colors if isinstance(colors, list) else [],
        "current_marketing_handler": answers.get("current_marketing_handler"),
        "current_marketing_spend": _number_or_none(answers.get("current_marketing_spend")),
        "current_reply_handler": answers.get("current_reply_handler"),
        "weekly_message_volume": _int_or_none(answers.get("weekly_message_volume")),
        "primary_pain_point": answers.get("primary_pain_point"),
        "primary_goal": answers.get("primary_goal"),
        "channels_requested": channels if isinstance(channels, list) else [],
        "owner_name": answers.get("owner_name"),
        "owner_contact": answers.get("owner_contact"),
        "paywall_status": "pending",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _get_onboarding_passport(owner_user_id: str) -> dict[str, Any] | None:
    result = (
        get_supabase()
        .table("brand_passports")
        .select("*")
        .eq("owner_user_id", owner_user_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _save_onboarding_passport(owner_user_id: str, org_id: str, answers: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    existing = _get_onboarding_passport(owner_user_id)
    payload = _onboarding_payload(owner_user_id, org_id, answers)

    if existing:
        payload["paywall_status"] = existing.get("paywall_status") or "pending"
        result = sb.table("brand_passports").update(payload).eq("id", existing["id"]).execute()
    else:
        result = sb.table("brand_passports").insert(payload).execute()
    return result.data[0]


def _update_onboarding_status(owner_user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    existing = _get_onboarding_passport(owner_user_id)
    if not existing:
        raise KeyError(owner_user_id)
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = (
        get_supabase()
        .table("brand_passports")
        .update(updates)
        .eq("id", existing["id"])
        .execute()
    )
    return result.data[0]


# ---------------------------------------------------------------------------
# Agent Switchboard + Squad Chat
# ---------------------------------------------------------------------------

@app.get("/api/onboarding/state/{owner_user_id}")
async def onboarding_state(owner_user_id: str, auth: AuthContext = Depends(require_authenticated_user)):
    _assert_onboarding_owner(auth, owner_user_id)
    try:
        return {"passport": _get_onboarding_passport(owner_user_id)}
    except Exception as e:
        if _is_missing_onboarding_migration(e):
            _raise_onboarding_migration_error()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/onboarding/passport")
async def save_onboarding_passport(
    request: OnboardingSaveRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_onboarding_owner(auth, request.owner_user_id)
    org_id = request.org_id or get_default_org_id()
    _assert_org_not_owned_by_other(auth.user_id, org_id)
    try:
        passport = _save_onboarding_passport(
            owner_user_id=request.owner_user_id,
            org_id=org_id,
            answers=request.answers,
        )
        return {"passport": passport}
    except Exception as e:
        if _is_missing_onboarding_migration(e):
            _raise_onboarding_migration_error()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/onboarding/complete")
async def complete_onboarding(
    request: OnboardingOwnerRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_onboarding_owner(auth, request.owner_user_id)
    if request.org_id:
        _assert_user_owns_org(auth.user_id, request.org_id)
    try:
        passport = _update_onboarding_status(
            request.owner_user_id,
            {"onboarding_completed_at": datetime.now(timezone.utc).isoformat()},
        )
        return {"passport": passport}
    except KeyError:
        raise HTTPException(status_code=404, detail="Onboarding passport not found")
    except Exception as e:
        if _is_missing_onboarding_migration(e):
            _raise_onboarding_migration_error()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/onboarding/stub-payment")
async def complete_stub_payment(
    request: OnboardingOwnerRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_onboarding_owner(auth, request.owner_user_id)
    if request.org_id:
        _assert_user_owns_org(auth.user_id, request.org_id)
    try:
        passport = _update_onboarding_status(
            request.owner_user_id,
            {"paywall_status": "stub_completed"},
        )
        return {"passport": passport}
    except KeyError:
        raise HTTPException(status_code=404, detail="Onboarding passport not found")
    except Exception as e:
        if _is_missing_onboarding_migration(e):
            _raise_onboarding_migration_error()
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/agent/{agent_slug}/message")
async def agent_message(
    agent_slug: str,
    request: AgentMessageRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    if agent_slug not in VALID_AGENTS:
        raise HTTPException(status_code=404, detail="Unknown agent")
    _assert_user_owns_org(auth.user_id, request.org_id)

    try:
        result = await handle_direct_agent_message(
            org_id=request.org_id,
            agent_slug=agent_slug,
            text=request.text,
            repo=get_switchboard_repo(),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/squad/message")
async def squad_message(
    request: SquadMessageRequest,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_user_owns_org(auth.user_id, request.org_id)
    return await handle_squad_owner_message(
        org_id=request.org_id,
        text=request.text,
        repo=get_switchboard_repo(),
        background_tasks=background_tasks,
    )


from lib.workflow_routes import create_workflow_router

app.include_router(create_workflow_router(
    lambda: get_switchboard_repo(), require_authenticated_user,
    lambda user_id, org_id: _assert_user_owns_org(user_id, org_id),
))


# ---------------------------------------------------------------------------
# Brand Passport CRUD
# ---------------------------------------------------------------------------

@app.get("/api/brand-passport/{brand_id}")
async def get_brand_passport(brand_id: str, auth: AuthContext = Depends(require_authenticated_user)):
    try:
        passport = _fetch_brand_passport(brand_id)
        _assert_user_owns_org(auth.user_id, passport["org_id"])
        return passport
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/brand-passport")
async def create_brand_passport(passport: dict, auth: AuthContext = Depends(require_authenticated_user)):
    try:
        passport["owner_user_id"] = auth.user_id
        if passport.get("org_id"):
            _assert_org_not_owned_by_other(auth.user_id, passport["org_id"])
        sb = get_supabase()
        result = sb.table("brand_passports").insert(passport).execute()
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/brand-passport/{brand_id}")
async def update_brand_passport(
    brand_id: str,
    updates: dict,
    auth: AuthContext = Depends(require_authenticated_user),
):
    try:
        sb = get_supabase()
        passport = _fetch_brand_passport(brand_id)
        _assert_user_owns_org(auth.user_id, passport["org_id"])
        updates.pop("owner_user_id", None)
        updates.pop("org_id", None)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = sb.table("brand_passports").update(updates).eq("id", brand_id).execute()
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


from services.sleyz.routes import create_sleyz_router
app.include_router(create_sleyz_router(lambda: get_switchboard_repo(), require_authenticated_user, lambda *args: _assert_user_owns_org(*args)))
from services.milo.routes import create_milo_router
app.include_router(create_milo_router(lambda: get_switchboard_repo(), require_authenticated_user, lambda *args: _assert_user_owns_org(*args)))
from services.vea.routes import create_vea_router
app.include_router(create_vea_router(lambda: get_switchboard_repo(), require_authenticated_user, lambda *args: _assert_user_owns_org(*args)))
