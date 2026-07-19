from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SETTINGS_SELECT = (
    "id,org_id,owner_user_id,brand_name,owner_name,owner_role,tone,"
    "target_audience,core_offer,target_location,channels_requested,"
    "paywall_status,selected_plan,updated_at"
)


class SettingsConflictError(RuntimeError):
    pass


class SettingsRepository:
    def __init__(self, client: Any) -> None:
        self.client = client

    def get_passport(self, org_id: str) -> dict[str, Any] | None:
        result = (
            self.client.table("brand_passports")
            .select(SETTINGS_SELECT)
            .eq("org_id", org_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def update_passport(
        self,
        org_id: str,
        updates: dict[str, Any],
        *,
        expected_updated_at: str,
    ) -> dict[str, Any]:
        payload = {
            **updates,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        result = (
            self.client.table("brand_passports")
            .update(payload)
            .eq("org_id", org_id)
            .eq("updated_at", expected_updated_at)
            .execute()
        )
        if not result.data:
            raise SettingsConflictError(org_id)
        return result.data[0]

    def get_memory(self, org_id: str) -> list[dict[str, Any]]:
        result = (
            self.client.table("agent_memory")
            .select("id,agent_slug,role,content,created_at")
            .eq("org_id", org_id)
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        return result.data or []
