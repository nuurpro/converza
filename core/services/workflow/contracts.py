"""Version 1 public payload contracts, mirrored by Web/lib/data/workflow.ts."""
from typing import Any, Literal, NotRequired, TypedDict

DraftState = Literal['PENDING_DRAFT','AWAITING_HITL','APPROVED','EDITED','REJECTED','PUBLISHED']
DeliveryState = Literal['idle','sending','failed','ambiguous','delivered']
GenerationState = Literal['pending','running','failed','completed']


class DraftRow(TypedDict):
    id: str
    org_id: str
    agent_slug: str
    status: DraftState
    revision: int
    draft_content: str
    final_content: NotRequired[str | None]
    inbound_text: NotRequired[str]
    prospect_id: NotRequired[str | None]
    created_at: NotRequired[str]
    updated_at: NotRequired[str]
    generation_status: NotRequired[GenerationState]
    generation_error: NotRequired[str | None]
    delivery_status: NotRequired[DeliveryState]
    delivery_error: NotRequired[str | None]
    delivery_attempt_id: NotRequired[str | None]
    delivery_claimed_at: NotRequired[str | None]
    delivery_receipt: NotRequired[dict[str, Any] | None]
    delivered_at: NotRequired[str | None]
    resolved_at: NotRequired[str | None]


class DurableEvent(TypedDict):
    schema_version: Literal[1]
    id: int
    org_id: str
    type: Literal['draft_transition','squad_message','agent_run_step']
    payload: dict[str, Any]
    created_at: str


class WorkspaceSnapshot(TypedDict):
    cursor: int
    drafts: list[DraftRow]
    messages: list[dict[str, Any]]
    steps: list[dict[str, Any]]
