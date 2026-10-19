"""Versioned SLEYZ contracts, mirrored by the web client."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


def intent_for_score(score: float) -> Literal['COLD', 'WARM', 'HOT']:
    if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError('Purchase readiness must be a finite number between zero and one')
    return 'HOT' if score >= .75 else 'WARM' if score >= .4 else 'COLD'


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Objection(Contract):
    type: Literal['price','trust','timing','fit','availability','payment','other']
    text: str = Field(min_length=1, max_length=4000)
    span: tuple[StrictInt, StrictInt]


class Classification(Contract):
    intent_score: float = Field(ge=0, le=1, strict=True)
    product_query: str = Field(default='', max_length=2000)
    quantity: StrictInt = Field(default=1, ge=1, le=100000)
    language: Literal['en','ru','uz'] = 'en'
    objections: list[Objection] = Field(default_factory=list, max_length=10)

    def validate_message(self, text: str):
        for objection in self.objections:
            start, end = objection.span
            if not 0 <= start < end <= len(text) or text[start:end] != objection.text:
                raise ValueError('Objection must be an exact buyer span')
        return self


class Citation(Contract):
    source_id: str
    revision: StrictInt = Field(ge=1)
    atom_index: StrictInt | None = Field(default=None, ge=0)
    span: tuple[StrictInt, StrictInt] | None = None


class ReplySelection(Contract):
    citations: list[Citation] = Field(default_factory=list, max_length=3)
    acknowledgement: Literal['thanks','concern','none'] = 'thanks'
    next_step: Literal['clarify_product','clarify_quantity','needs','buy','none'] = 'needs'
    include_price: bool = True
    include_stock: bool = True
    include_description: bool = True
    apply_corrections: bool = True


class ProductSnapshot(Contract):
    id: str
    sku: str | None = None
    name: str
    description: str = ''
    price: str | None = None
    currency: str
    stock_count: StrictInt | None = Field(default=None, ge=0)
    revision: StrictInt = Field(ge=1)
    checkout_url_template: str | None = None


class SleyzDraftArtifact(Contract):
    schema_version: Literal[1] = 1
    customer_handle: str
    platform: Literal['telegram','instagram']
    incoming_message: str
    intent_score: float = Field(ge=0, le=1)
    intent: Literal['COLD','WARM','HOT']
    detected_objection: str | None
    cited_brand_passport_atoms: list[Citation]
    draft_reply: str = Field(min_length=1, max_length=4000)
    checkout_link: str | None
    product_snapshot: list[ProductSnapshot]
    quantity: StrictInt = Field(ge=1)
    operator_notes: list[str]
