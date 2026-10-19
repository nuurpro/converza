from __future__ import annotations

import uuid
import asyncio
import json
from copy import deepcopy
from starlette.concurrency import run_in_threadpool

from services.workflow.state import WorkflowConflict, apply_transition
from datetime import datetime, timezone
from typing import Any, Protocol


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SwitchboardRepository(Protocol):
    async def get_brand_passport(self, org_id: str) -> dict[str, Any]: ...
    async def get_agent_memory(self, org_id: str, agent_slug: str, limit: int = 20) -> list[dict[str, Any]]: ...
    async def insert_agent_memory(self, org_id: str, agent_slug: str, role: str, content: str) -> dict[str, Any]: ...
    async def create_agent_run(self, org_id: str, agent_slug: str, triggered_by: str, input_text: str) -> str: ...
    async def update_agent_run(self, run_id: str, updates: dict[str, Any]) -> None: ...
    async def insert_agent_run_step(self, agent_run_id: str, org_id: str, agent_slug: str, step_label: str, step_status: str, detail: str | None = None) -> dict[str, Any]: ...
    async def insert_squad_message(self, org_id: str, sender_slug: str, content: str, mentions: list[str] | None = None, related_run_id: str | None = None, hitl_draft_id: str | None = None) -> dict[str, Any]: ...
    async def create_draft(self, org_id: str, agent_slug: str, inbound_text: str, draft_content: str, prospect_id: str | None = None) -> dict[str, Any]: ...
    async def update_draft(self, draft_id: str, updates: dict[str, Any]) -> dict[str, Any]: ...
    async def get_draft(self, draft_id: str) -> dict[str, Any] | None: ...
    async def get_run_id_for_draft(self, draft_id: str) -> str | None: ...
    async def get_dashboard_stats(self, org_id: str) -> list[dict[str, str]]: ...
    async def transition_draft(self, org_id: str, draft_id: str, action: str, expected_revision: int, idempotency_key: str, edited_content: str | None = None, receipt: dict | None = None, error: str | None = None) -> dict[str, Any]: ...
    async def snapshot(self, org_id: str) -> dict[str, Any]: ...
    async def read_events(self, org_id: str, after: int, limit: int = 200) -> list[dict[str, Any]]: ...
    async def mark_resolved(self, org_id: str, draft_id: str, expected_revision: int, idempotency_key: str) -> dict[str, Any]: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self.brand_passports: dict[str, dict[str, Any]] = {}
        self.agent_memory: list[dict[str, Any]] = []
        self.agent_runs: list[dict[str, Any]] = []
        self.agent_run_steps: list[dict[str, Any]] = []
        self.squad_messages: list[dict[str, Any]] = []
        self.drafts: list[dict[str, Any]] = []
        self.events = []
        self.idempotency = {}
        self._lock = asyncio.Lock()

    def _event(self, org_id, kind, row):
        seq = 1 + max((e['id'] for e in self.events if e['org_id'] == org_id), default=0)
        self.events.append({'schema_version': 1, 'id': seq, 'org_id': org_id,
                            'type': kind, 'payload': {'row': deepcopy(row)}, 'created_at': utc_now_iso()})

    async def transition_draft(self, org_id, draft_id, action, expected_revision, idempotency_key,
                               edited_content=None, receipt=None, error=None):
        if not idempotency_key:
            raise ValueError('idempotency_key is required')
        fingerprint = json.dumps([draft_id, action, expected_revision, edited_content, receipt, error], sort_keys=True)
        async with self._lock:
            cache_key = (org_id, idempotency_key)
            if cache_key in self.idempotency:
                previous, result = self.idempotency[cache_key]
                if fingerprint != previous:
                    raise WorkflowConflict('Idempotency key reused with a different request')
                return deepcopy(result)
            row = next((r for r in self.drafts if r['id'] == draft_id and r['org_id'] == org_id), None)
            if not row:
                raise KeyError(draft_id)
            if row['revision'] != expected_revision:
                raise WorkflowConflict('Draft revision conflict')
            updated = apply_transition(row, action, edited_content=edited_content, receipt=receipt, error=error)
            row.update(updated)
            self._event(org_id, 'draft_transition', row)
            if action in ('approve', 'edit', 'reject'):
                run_id = await self.get_run_id_for_draft(draft_id)
                if run_id:
                    await self.update_agent_run(run_id, {'status':'failed' if action == 'reject' else 'completed', 'completed_at':utc_now_iso()})
                await self.insert_squad_message(org_id, 'converza', f'HITL {row["status"]}: draft {draft_id}', related_run_id=run_id, hitl_draft_id=draft_id)
            self.idempotency[cache_key] = (fingerprint, deepcopy(row))
            return deepcopy(row)

    async def mark_resolved(self, org_id, draft_id, expected_revision, idempotency_key):
        return await self.transition_draft(org_id, draft_id, 'resolve', expected_revision, idempotency_key)

    async def snapshot(self, org_id):
        async with self._lock:
            return deepcopy({'cursor': max((e['id'] for e in self.events if e['org_id'] == org_id), default=0),
                'drafts': [r for r in self.drafts if r['org_id'] == org_id],
                'messages': [r for r in self.squad_messages if r['org_id'] == org_id],
                'steps': [r for r in self.agent_run_steps if r['org_id'] == org_id]})

    async def read_events(self, org_id, after, limit=200):
        return deepcopy([e for e in self.events if e['org_id'] == org_id and e['id'] > after][:max(1,min(limit,1000))])

    def seed_brand_passport(self, org_id: str, passport: dict[str, Any]) -> None:
        self.brand_passports[org_id] = {"org_id": org_id, **passport}

    async def get_brand_passport(self, org_id: str) -> dict[str, Any]:
        return self.brand_passports.get(org_id, {"org_id": org_id, "brand_name": "Unknown Brand"})

    async def get_agent_memory(self, org_id: str, agent_slug: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.agent_memory
            if row["org_id"] == org_id and row["agent_slug"] == agent_slug
        ]
        return rows[-limit:]

    async def insert_agent_memory(self, org_id: str, agent_slug: str, role: str, content: str) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "agent_slug": agent_slug,
            "role": role,
            "content": content,
            "created_at": utc_now_iso(),
        }
        self.agent_memory.append(row)
        return row

    async def create_agent_run(self, org_id: str, agent_slug: str, triggered_by: str, input_text: str) -> str:
        row = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "agent_slug": agent_slug,
            "triggered_by": triggered_by,
            "input_text": input_text,
            "status": "running",
            "created_at": utc_now_iso(),
            "completed_at": None,
        }
        self.agent_runs.append(row)
        return row["id"]

    async def update_agent_run(self, run_id: str, updates: dict[str, Any]) -> None:
        for row in self.agent_runs:
            if row["id"] == run_id:
                row.update(updates)
                return

    async def insert_agent_run_step(
        self,
        agent_run_id: str,
        org_id: str,
        agent_slug: str,
        step_label: str,
        step_status: str,
        detail: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "agent_run_id": agent_run_id,
            "org_id": org_id,
            "agent_slug": agent_slug,
            "step_label": step_label,
            "step_status": step_status,
            "detail": detail,
            "created_at": utc_now_iso(),
        }
        self.agent_run_steps.append(row)
        self._event(org_id, "agent_run_step", row)
        return deepcopy(row)

    async def insert_squad_message(
        self,
        org_id: str,
        sender_slug: str,
        content: str,
        mentions: list[str] | None = None,
        related_run_id: str | None = None,
        hitl_draft_id: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "sender_slug": sender_slug,
            "content": content,
            "mentions": mentions or [],
            "related_run_id": related_run_id,
            "hitl_draft_id": hitl_draft_id,
            "created_at": utc_now_iso(),
        }
        self.squad_messages.append(row)
        self._event(org_id, "squad_message", row)
        return deepcopy(row)

    async def create_draft(
        self,
        org_id: str,
        agent_slug: str,
        inbound_text: str,
        draft_content: str,
        prospect_id: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "agent_slug": agent_slug,
            "prospect_id": prospect_id,
            "inbound_text": inbound_text,
            "draft_content": draft_content,
            "final_content": None,
            "status": "PENDING_DRAFT",
            "revision": 1, "generation_error": None, "generation_status":"pending",
            "delivery_status": "idle", "delivery_error": None,
            "delivery_receipt": None, "delivered_at": None, "resolved_at": None,
            "updated_at": utc_now_iso(),
            "created_at": utc_now_iso(),
            "decided_at": None,
        }
        self.drafts.append(row)
        self._event(org_id, "draft_transition", row)
        return deepcopy(row)

    async def update_draft(self, draft_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        if set(updates) & {"status", "final_content", "resolved_at", "delivered_at", "delivery_receipt"}:
            raise WorkflowConflict("Use transition_draft for lifecycle mutations")
        for row in self.drafts:
            if row["id"] == draft_id:
                row.update(updates)
                return row
        raise KeyError(draft_id)

    async def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        return deepcopy(next((row for row in self.drafts if row["id"] == draft_id), None))

    async def get_run_id_for_draft(self, draft_id: str) -> str | None:
        for row in self.squad_messages:
            if row.get("hitl_draft_id") == draft_id and row.get("related_run_id"):
                return row["related_run_id"]
        return None

    async def get_dashboard_stats(self, org_id: str) -> list[dict[str, str]]:
        running = sum(1 for run in self.agent_runs if run["org_id"] == org_id and run["status"] == "running")
        pending = sum(1 for draft in self.drafts if draft["org_id"] == org_id and draft["status"] == "AWAITING_HITL")
        completed = sum(1 for run in self.agent_runs if run["org_id"] == org_id and run["status"] == "completed")
        return [
            {"value": str(running), "label": "Runs active"},
            {"value": str(pending), "label": "Drafts pending"},
            {"value": str(completed), "label": "Completed runs"},
            {"value": str(sum(row["org_id"] == org_id for row in self.squad_messages)), "label": "Squad messages"},
        ]


class SupabaseRepository:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def transition_draft(self, org_id, draft_id, action, expected_revision, idempotency_key,
                               edited_content=None, receipt=None, error=None):
        try:
            result = await run_in_threadpool(self.client.rpc('workflow_transition', {'p_org_id':org_id,'p_draft_id':draft_id,
                'p_action':action,'p_expected_revision':expected_revision,'p_idempotency_key':idempotency_key,
                'p_content':edited_content,'p_receipt':receipt,'p_error':error}).execute)
            return result.data
        except Exception as exc:
            if 'workflow_not_found' in str(exc):
                raise KeyError(draft_id) from exc
            if 'workflow_conflict' in str(exc):
                raise WorkflowConflict(str(exc)) from exc
            raise

    async def mark_resolved(self, org_id, draft_id, expected_revision, idempotency_key):
        return await self.transition_draft(org_id, draft_id, 'resolve', expected_revision, idempotency_key)

    async def snapshot(self, org_id):
        result = await run_in_threadpool(self.client.rpc('workflow_snapshot', {'p_org_id':org_id}).execute)
        return result.data

    async def read_events(self, org_id, after, limit=200):
        result = await run_in_threadpool(self.client.rpc('workflow_read_events', {'p_org_id':org_id,'p_after':after,'p_limit':limit}).execute)
        return result.data or []

    async def get_brand_passport(self, org_id: str) -> dict[str, Any]:
        result = (
            self.client.table("brand_passports")
            .select("*")
            .eq("org_id", org_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else {"org_id": org_id, "brand_name": "Unknown Brand"}

    async def get_agent_memory(self, org_id: str, agent_slug: str, limit: int = 20) -> list[dict[str, Any]]:
        result = (
            self.client.table("agent_memory")
            .select("*")
            .eq("org_id", org_id)
            .eq("agent_slug", agent_slug)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(reversed(result.data or []))

    async def insert_agent_memory(self, org_id: str, agent_slug: str, role: str, content: str) -> dict[str, Any]:
        result = self.client.table("agent_memory").insert({
            "org_id": org_id,
            "agent_slug": agent_slug,
            "role": role,
            "content": content,
        }).execute()
        return result.data[0]

    async def create_agent_run(self, org_id: str, agent_slug: str, triggered_by: str, input_text: str) -> str:
        result = self.client.table("agent_runs").insert({
            "org_id": org_id,
            "agent_slug": agent_slug,
            "triggered_by": triggered_by,
            "input_text": input_text,
            "status": "running",
        }).execute()
        return result.data[0]["id"]

    async def update_agent_run(self, run_id: str, updates: dict[str, Any]) -> None:
        self.client.table("agent_runs").update(updates).eq("id", run_id).execute()

    async def insert_agent_run_step(
        self,
        agent_run_id: str,
        org_id: str,
        agent_slug: str,
        step_label: str,
        step_status: str,
        detail: str | None = None,
    ) -> dict[str, Any]:
        result = self.client.table("agent_run_steps").insert({
            "agent_run_id": agent_run_id,
            "org_id": org_id,
            "agent_slug": agent_slug,
            "step_label": step_label,
            "step_status": step_status,
            "detail": detail,
        }).execute()
        return result.data[0]

    async def insert_squad_message(
        self,
        org_id: str,
        sender_slug: str,
        content: str,
        mentions: list[str] | None = None,
        related_run_id: str | None = None,
        hitl_draft_id: str | None = None,
    ) -> dict[str, Any]:
        result = self.client.table("squad_messages").insert({
            "org_id": org_id,
            "sender_slug": sender_slug,
            "content": content,
            "mentions": mentions or [],
            "related_run_id": related_run_id,
            "hitl_draft_id": hitl_draft_id,
        }).execute()
        return result.data[0]

    async def create_draft(
        self,
        org_id: str,
        agent_slug: str,
        inbound_text: str,
        draft_content: str,
        prospect_id: str | None = None,
    ) -> dict[str, Any]:
        result = self.client.table("drafts").insert({
            "org_id": org_id,
            "agent_slug": agent_slug,
            "prospect_id": prospect_id,
            "inbound_text": inbound_text,
            "draft_content": draft_content,
            "status": "PENDING_DRAFT",
            "revision": 1, "generation_error": None, "generation_status":"pending",
            "delivery_status": "idle", "delivery_error": None,
            "delivery_receipt": None, "delivered_at": None, "resolved_at": None,
            "updated_at": utc_now_iso(),
        }).execute()
        return result.data[0]

    async def update_draft(self, draft_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        if set(updates) & {"status", "final_content", "resolved_at", "delivered_at", "delivery_receipt"}:
            raise WorkflowConflict("Use transition_draft for lifecycle mutations")
        result = self.client.table("drafts").update(updates).eq("id", draft_id).execute()
        return result.data[0]

    async def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        result = self.client.table("drafts").select("*").eq("id", draft_id).limit(1).execute()
        return result.data[0] if result.data else None

    async def get_run_id_for_draft(self, draft_id: str) -> str | None:
        result = (
            self.client.table("squad_messages")
            .select("related_run_id")
            .eq("hitl_draft_id", draft_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        for row in result.data or []:
            if row.get("related_run_id"):
                return row["related_run_id"]
        return None

    async def get_dashboard_stats(self, org_id: str) -> list[dict[str, str]]:
        runs = self.client.table("agent_runs").select("id,status").eq("org_id", org_id).execute().data or []
        drafts = self.client.table("drafts").select("id,status").eq("org_id", org_id).execute().data or []
        messages = self.client.table("squad_messages").select("id").eq("org_id", org_id).execute().data or []
        active = sum(1 for run in runs if run.get("status") == "running")
        completed = sum(1 for run in runs if run.get("status") == "completed")
        pending = sum(1 for draft in drafts if draft.get("status") == "AWAITING_HITL")
        return [
            {"value": str(active), "label": "Runs active"},
            {"value": str(pending), "label": "Drafts pending"},
            {"value": str(completed), "label": "Completed runs"},
            {"value": str(len(messages)), "label": "Squad messages"},
        ]
