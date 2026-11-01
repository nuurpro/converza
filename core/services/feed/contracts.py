"""Read-only approval projection; mutations retain their original contracts."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ReviewRestrictions(Contract):
    can_approve: bool
    can_edit: bool
    can_reject: bool
    reasons: list[str]


class WorkflowPayload(Contract):
    draft: dict


class MiloPayload(Contract):
    campaign: dict
    review_href: str


class FeedIdentity(Contract):
    id: str
    source_id: str
    revision: int = Field(ge=1)
    created_at: str
    restrictions: ReviewRestrictions


class WorkflowItem(FeedIdentity):
    kind: Literal['workflow']
    payload: WorkflowPayload


class MiloItem(FeedIdentity):
    kind: Literal['milo']
    payload: MiloPayload


PendingItem = Annotated[WorkflowItem | MiloItem, Field(discriminator='kind')]


class PendingPage(Contract):
    items: list[PendingItem]
    next_cursor: str | None
    snapshot_at: str
