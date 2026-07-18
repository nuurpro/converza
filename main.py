import json
import asyncio
import os
import re
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
from lib.marketing_calendar import (
    calculate_resource_commitment,
    check_platform_overreach,
    derive_literacy_level,
    generate_calendar_skeleton,
    generate_day_detail,
)
from lib.marketing_calendar_repository import MarketingCalendarRepository
from lib.narration import narrate_step
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


class MarketingCalendarInterviewRequest(BaseModel):
    org_id: str
    target_audience: str
    tone: list[str]
    core_offer: str
    platforms: list[str]
    hours_per_week: float
    duration_days: int = 14
    has_tracked_metrics_before: bool
    current_process: str
    overrode_platform_limit: bool = False


class MarketingCalendarActionRequest(BaseModel):
    org_id: str


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Converza Co-Pilot", version="0.1.0")

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


def get_marketing_calendar_repo() -> MarketingCalendarRepository:
    return MarketingCalendarRepository(get_supabase())


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


def _missing_schema_column(error: Exception) -> str | None:
    message = str(error)
    if "PGRST204" not in message and "Could not find the" not in message:
        return None
    marker = "Could not find the '"
    if marker not in message:
        return None
    return message.split(marker, 1)[1].split("'", 1)[0]


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

    def write(next_payload: dict[str, Any]):
        if existing:
            next_payload["paywall_status"] = existing.get("paywall_status") or "pending"
            return sb.table("brand_passports").update(next_payload).eq("id", existing["id"]).execute()
        return sb.table("brand_passports").insert(next_payload).execute()

    try:
        result = write(payload)
    except Exception as e:
        missing_column = _missing_schema_column(e)
        if missing_column == "hex_colors":
            fallback_payload = {key: value for key, value in payload.items() if key != missing_column}
            result = write(fallback_payload)
        else:
            raise
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


def _calendar_day(calendar: dict[str, Any], day_number: int) -> dict[str, Any]:
    for day in calendar.get("days") or []:
        if int(day.get("day_number", 0)) == day_number:
            return day
    raise KeyError(f"Calendar day {day_number} not found")


def _video_url_from_draft(draft: dict[str, Any]) -> str | None:
    content = str(draft.get("draft_content") or "")
    match = re.search(r"Preview URL:\s*(\S+)", content)
    return match.group(1) if match else None


def _is_missing_calendar_migration(error: Exception) -> bool:
    message = str(error)
    return "marketing_calendars" in message and ("PGRST" in message or "relation" in message)


def _sync_calendar_hitl(draft_id: str, action: str) -> None:
    try:
        updates: dict[str, Any] = {
            "status": "failed" if action == "reject" else "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        get_marketing_calendar_repo().update_day_by_draft(draft_id, updates)
    except Exception as error:
        if not _is_missing_calendar_migration(error):
            raise


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


# ---------------------------------------------------------------------------
# Managed Marketing Calendar
# ---------------------------------------------------------------------------

@app.get("/api/marketing-calendar/{org_id}")
async def get_marketing_calendar(
    org_id: str,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_user_owns_org(auth.user_id, org_id)
    try:
        return {"calendar": get_marketing_calendar_repo().get_current(org_id)}
    except Exception as error:
        if _is_missing_calendar_migration(error):
            raise HTTPException(
                status_code=503,
                detail="Managed calendar migration is pending. Run migrations/005_managed_marketing_calendar.sql in Supabase.",
            )
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/api/marketing-calendar/interview")
async def complete_marketing_calendar_interview(
    request: MarketingCalendarInterviewRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_user_owns_org(auth.user_id, request.org_id)
    if request.duration_days not in (14, 30):
        raise HTTPException(status_code=400, detail="duration_days must be 14 or 30")
    if not request.platforms:
        raise HTTPException(status_code=400, detail="Select at least one platform")
    if not request.target_audience.strip() or not request.core_offer.strip() or not request.tone:
        raise HTTPException(status_code=400, detail="Target audience, offer, and tone are required")

    signals = {
        "platforms_requested": len(request.platforms),
        "selected_platforms": request.platforms,
        "overrode_platform_limit": request.overrode_platform_limit,
        "has_tracked_metrics_before": request.has_tracked_metrics_before,
        "current_process": request.current_process,
    }
    literacy_level = derive_literacy_level(signals)
    constraint = check_platform_overreach(request.platforms, literacy_level)
    if constraint and not request.overrode_platform_limit:
        raise HTTPException(status_code=409, detail=constraint)

    try:
        resource = calculate_resource_commitment(request.hours_per_week, request.duration_days)
        repo = get_marketing_calendar_repo()
        passport = repo.save_interview(
            org_id=request.org_id,
            target_audience=request.target_audience.strip(),
            tone=request.tone,
            core_offer=request.core_offer.strip(),
            platforms=request.platforms,
            literacy_level=literacy_level,
            signals=signals,
        )
        switchboard_repo = get_switchboard_repo()
        run_id = await switchboard_repo.create_agent_run(
            request.org_id,
            "milo",
            "owner",
            f"Build a {request.duration_days}-day managed marketing calendar",
        )
        try:
            async with narrate_step(
                repo=switchboard_repo,
                org_id=request.org_id,
                agent_slug="milo",
                run_id=run_id,
                step_label=f"Building {request.duration_days}-day calendar",
                completed_detail=f"{request.duration_days} themes planned",
            ):
                days = await generate_calendar_skeleton(
                    passport=passport,
                    duration_days=request.duration_days,
                    platforms=request.platforms,
                    target_video_count=resource["target_video_count"],
                )
            await switchboard_repo.update_agent_run(
                run_id,
                {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()},
            )
        except Exception:
            await switchboard_repo.update_agent_run(
                run_id,
                {"status": "failed", "completed_at": datetime.now(timezone.utc).isoformat()},
            )
            raise
        calendar = repo.create(
            org_id=request.org_id,
            duration_days=request.duration_days,
            platforms=request.platforms,
            hours_per_week=resource["hours_per_week"],
            target_video_count=resource["target_video_count"],
            days=days,
        )
        return {
            "calendar": calendar,
            "literacy_level": literacy_level,
            "literacy_signals": signals,
            "resource_commitment": resource,
            "platform_constraint": constraint,
        }
    except HTTPException:
        raise
    except Exception as error:
        if _is_missing_calendar_migration(error):
            raise HTTPException(
                status_code=503,
                detail="Managed calendar migration is pending. Run migrations/005_managed_marketing_calendar.sql in Supabase.",
            )
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/api/marketing-calendar/{calendar_id}/days/{day_number}/detail")
async def generate_marketing_calendar_day_detail(
    calendar_id: str,
    day_number: int,
    request: MarketingCalendarActionRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_user_owns_org(auth.user_id, request.org_id)
    repo = get_marketing_calendar_repo()
    try:
        calendar = repo.get_by_id(calendar_id)
        if not calendar:
            raise HTTPException(status_code=404, detail="Marketing calendar not found")
        if calendar["org_id"] != request.org_id:
            raise HTTPException(status_code=403, detail="Calendar does not belong to this org")
        day = _calendar_day(calendar, day_number)
        if day.get("script"):
            return {"calendar": calendar, "day": day}
        passport = repo.get_passport(request.org_id)
        if not passport:
            raise HTTPException(status_code=404, detail="Brand Passport not found")
        switchboard_repo = get_switchboard_repo()
        run_id = await switchboard_repo.create_agent_run(
            request.org_id,
            "milo",
            "owner",
            f"Write calendar day {day_number}: {day['theme']}",
        )
        try:
            async with narrate_step(
                repo=switchboard_repo,
                org_id=request.org_id,
                agent_slug="milo",
                run_id=run_id,
                step_label=f"Writing day {day_number} script",
                completed_detail=f"theme matched: {day['theme']}",
            ):
                detail = await generate_day_detail(
                    passport=passport,
                    day=day,
                    platforms=calendar["platforms"],
                )
            await switchboard_repo.update_agent_run(
                run_id,
                {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()},
            )
        except Exception:
            await switchboard_repo.update_agent_run(
                run_id,
                {"status": "failed", "completed_at": datetime.now(timezone.utc).isoformat()},
            )
            raise
        updated = repo.update_day(
            calendar,
            day_number,
            {"script": detail["script"], "status": "draft", "milo_run_id": run_id},
        )
        return {"calendar": updated, "day": _calendar_day(updated, day_number)}
    except HTTPException:
        raise
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/api/marketing-calendar/{calendar_id}/days/{day_number}/approve")
async def approve_marketing_calendar_day(
    calendar_id: str,
    day_number: int,
    request: MarketingCalendarActionRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_user_owns_org(auth.user_id, request.org_id)
    repo = get_marketing_calendar_repo()
    calendar = repo.get_by_id(calendar_id)
    if not calendar:
        raise HTTPException(status_code=404, detail="Marketing calendar not found")
    if calendar["org_id"] != request.org_id:
        raise HTTPException(status_code=403, detail="Calendar does not belong to this org")
    day = _calendar_day(calendar, day_number)
    script = str(day.get("script") or "").strip()
    if not script:
        raise HTTPException(status_code=409, detail="Generate this day's script before approving it")

    repo.update_day(
        calendar,
        day_number,
        {
            "status": "rendering",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "render_error": None,
        },
    )
    try:
        result = await handle_direct_agent_message(
            org_id=request.org_id,
            agent_slug="vea",
            text=(
                f"Render calendar day {day_number}: {day['theme']}. "
                f"Use this approved script as the source: {script}"
            ),
            repo=get_switchboard_repo(),
        )
        draft = repo.find_render_for_run(result["run_id"])
        if not draft:
            raise RuntimeError("Vea completed without creating a review draft")
        video_url = _video_url_from_draft(draft)
        if not video_url:
            raise RuntimeError("Vea review draft did not contain a video URL")
        current = repo.get_by_id(calendar_id)
        updated = repo.update_day(
            current,
            day_number,
            {
                "status": "awaiting_hitl",
                "video_url": video_url,
                "hitl_draft_id": draft["id"],
                "agent_run_id": result["run_id"],
            },
        )
        return {"calendar": updated, "day": _calendar_day(updated, day_number), "draft": draft}
    except Exception as error:
        current = repo.get_by_id(calendar_id)
        if current:
            repo.update_day(
                current,
                day_number,
                {"status": "failed", "render_error": str(error)},
            )
        raise HTTPException(status_code=500, detail=str(error))

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


@app.get("/api/squad/stream")
async def squad_stream(org_id: str, auth: AuthContext = Depends(require_authenticated_user)):
    _assert_user_owns_org(auth.user_id, org_id)
    def fetch_stream_rows(
        table_name: str,
        last_created_at: str | None,
    ) -> list[dict]:
        query = (
            get_supabase()
            .table(table_name)
            .select("*")
            .eq("org_id", org_id)
        )
        if last_created_at:
            result = (
                query.gte("created_at", last_created_at)
                .order("created_at", desc=False)
                .limit(100)
                .execute()
            )
            return result.data or []

        result = (
            query.order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        return list(reversed(result.data or []))

    async def events() -> AsyncGenerator[str, None]:
        seen_messages: set[str] = set()
        seen_steps: set[str] = set()
        last_message_created_at: str | None = None
        last_step_created_at: str | None = None
        while True:
            try:
                messages = fetch_stream_rows("squad_messages", last_message_created_at)
                for row in messages:
                    if row["id"] in seen_messages:
                        continue
                    seen_messages.add(row["id"])
                    last_message_created_at = row.get("created_at") or last_message_created_at
                    yield f"data: {json.dumps({'type': 'squad_message', 'row': row}, default=str)}\n\n"

                steps = fetch_stream_rows("agent_run_steps", last_step_created_at)
                for row in steps:
                    if row["id"] in seen_steps:
                        continue
                    seen_steps.add(row["id"])
                    last_step_created_at = row.get("created_at") or last_step_created_at
                    yield f"data: {json.dumps({'type': 'agent_run_step', 'row': row}, default=str)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _get_draft_org_id(draft_id: str) -> str:
    draft = get_supabase().table("drafts").select("org_id").eq("id", draft_id).limit(1).execute()
    if not draft.data:
        raise KeyError(draft_id)
    return draft.data[0]["org_id"]


@app.post("/api/hitl/{draft_id}/approve")
async def hitl_approve(draft_id: str, auth: AuthContext = Depends(require_authenticated_user)):
    try:
        _assert_user_owns_org(auth.user_id, _get_draft_org_id(draft_id))
        result = await resolve_hitl(
            draft_id=draft_id,
            action="approve",
            repo=get_switchboard_repo(),
        )
        _sync_calendar_hitl(draft_id, "approve")
        return result
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/api/hitl/{draft_id}/reject")
async def hitl_reject(draft_id: str, auth: AuthContext = Depends(require_authenticated_user)):
    try:
        _assert_user_owns_org(auth.user_id, _get_draft_org_id(draft_id))
        result = await resolve_hitl(
            draft_id=draft_id,
            action="reject",
            repo=get_switchboard_repo(),
        )
        _sync_calendar_hitl(draft_id, "reject")
        return result
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/api/hitl/{draft_id}/edit")
async def hitl_edit(
    draft_id: str,
    request: HitlEditRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    try:
        _assert_user_owns_org(auth.user_id, _get_draft_org_id(draft_id))
        result = await resolve_hitl(
            draft_id=draft_id,
            action="edit",
            repo=get_switchboard_repo(),
            edited_content=request.final_content,
        )
        _sync_calendar_hitl(draft_id, "edit")
        return result
    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(status_code=404, detail="Draft not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/dashboard/{org_id}/stats")
async def dashboard_stats(org_id: str, auth: AuthContext = Depends(require_authenticated_user)):
    _assert_user_owns_org(auth.user_id, org_id)
    try:
        return {"stats": await get_switchboard_repo().get_dashboard_stats(org_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


