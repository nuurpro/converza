from datetime import datetime, timezone
from typing import Any


class MarketingCalendarRepository:
    def __init__(self, client: Any) -> None:
        self.client = client

    def get_current(self, org_id: str) -> dict[str, Any] | None:
        result = (
            self.client.table("marketing_calendars")
            .select("*")
            .eq("org_id", org_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_passport(self, org_id: str) -> dict[str, Any] | None:
        result = (
            self.client.table("brand_passports")
            .select("*")
            .eq("org_id", org_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_by_id(self, calendar_id: str) -> dict[str, Any] | None:
        result = self.client.table("marketing_calendars").select("*").eq("id", calendar_id).limit(1).execute()
        return result.data[0] if result.data else None

    def create(
        self,
        *,
        org_id: str,
        duration_days: int,
        platforms: list[str],
        hours_per_week: float,
        target_video_count: int,
        days: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result = self.client.table("marketing_calendars").insert(
            {
                "org_id": org_id,
                "duration_days": duration_days,
                "platforms": platforms,
                "hours_per_week": hours_per_week,
                "target_video_count": target_video_count,
                "days": days,
            }
        ).execute()
        return result.data[0]

    def update(self, calendar_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        payload = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
        result = self.client.table("marketing_calendars").update(payload).eq("id", calendar_id).execute()
        if not result.data:
            raise KeyError(calendar_id)
        return result.data[0]

    def update_day(self, calendar: dict[str, Any], day_number: int, updates: dict[str, Any]) -> dict[str, Any]:
        days = [dict(day) for day in calendar.get("days") or []]
        for day in days:
            if int(day.get("day_number", 0)) == day_number:
                day.update(updates)
                return self.update(calendar["id"], {"days": days})
        raise KeyError(f"calendar day {day_number}")

    def update_day_by_draft(self, draft_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        result = self.client.table("marketing_calendars").select("*").contains("days", [{"hitl_draft_id": draft_id}]).limit(1).execute()
        if not result.data:
            return None
        calendar = result.data[0]
        for day in calendar.get("days") or []:
            if day.get("hitl_draft_id") == draft_id:
                return self.update_day(calendar, int(day["day_number"]), updates)
        return None

    def save_interview(
        self,
        *,
        org_id: str,
        target_audience: str,
        tone: list[str],
        core_offer: str,
        platforms: list[str],
        literacy_level: str,
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "target_audience": target_audience,
            "tone": ", ".join(tone),
            "core_offer": core_offer,
            "channels_requested": platforms,
            "marketing_literacy_level": literacy_level,
            "marketing_literacy_signals": signals,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        result = self.client.table("brand_passports").update(payload).eq("org_id", org_id).execute()
        if not result.data:
            raise KeyError(org_id)
        return result.data[0]

    def find_render_for_run(self, run_id: str) -> dict[str, Any] | None:
        message_result = (
            self.client.table("squad_messages")
            .select("hitl_draft_id")
            .eq("related_run_id", run_id)
            .not_.is_("hitl_draft_id", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not message_result.data:
            return None
        draft_id = message_result.data[0].get("hitl_draft_id")
        draft_result = self.client.table("drafts").select("*").eq("id", draft_id).limit(1).execute()
        return draft_result.data[0] if draft_result.data else None
