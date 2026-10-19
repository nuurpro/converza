"""Versioned campaign contracts shared at service and UI boundaries."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

LANGUAGES = ('en', 'ru', 'uz')
TOPICS = ('price', 'durability', 'trust', 'timing', 'fit', 'availability', 'payment', 'delivery', 'returns', 'usability', 'other')


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Persona(Contract):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200, pattern=r'\S')
    description: str = Field(min_length=1, max_length=2000, pattern=r'\S')


class ProofReference(Contract):
    source_id: str = Field(min_length=1)
    revision: StrictInt = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)


class ProofPoint(ProofReference):
    id: str = Field(min_length=1, max_length=100)
    product_id: str | None = None
    objection_topics: list[str] = Field(default_factory=list, max_length=11)
    confirmed_by: str | None = None
    confirmed_at: str | None = None


class BuyerQuote(Contract):
    source_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=4000)


class Hook(Contract):
    framework: Literal['A', 'B', 'C']
    text: str = Field(min_length=1, max_length=1500, pattern=r'\S')


class VideoScene(Contract):
    spoken_narration: str = Field(min_length=1, max_length=1500, pattern=r'\S')
    visual_broll_cues: str = Field(min_length=1, max_length=1500, pattern=r'\S')
    on_screen_text: str = Field(max_length=500)


class SocialCaptions(Contract):
    instagram: str = Field(min_length=1, max_length=2200, pattern=r'\S')
    telegram: str = Field(min_length=1, max_length=4000, pattern=r'\S')
    tiktok: str = Field(min_length=1, max_length=2200, pattern=r'\S')


class MiloCampaignArtifact(Contract):
    schema_version: Literal[1] = 1
    trigger_reason: str = Field(min_length=1, max_length=500)
    target_persona: Persona
    language: Literal['en', 'ru', 'uz']
    hooks: list[Hook] = Field(min_length=3, max_length=3)
    video_script: list[VideoScene] = Field(min_length=1, max_length=12)
    social_captions: SocialCaptions
    buyer_quotes: list[BuyerQuote] = Field(min_length=1, max_length=10)
    proof_references: list[ProofReference] = Field(min_length=1, max_length=20)
    brand_revision: StrictInt = Field(ge=1)

    @model_validator(mode='after')
    def framework_matrix(self):
        if [hook.framework for hook in self.hooks] != ['A', 'B', 'C']:
            raise ValueError('Hooks must contain frameworks A, B, C in that order')
        return self


class MiloCreativeDraft(Contract):
    """Inference writes copy; code attaches authoritative evidence provenance."""
    target_persona: Persona
    hooks: list[Hook] = Field(min_length=3, max_length=3)
    video_script: list[VideoScene] = Field(min_length=1, max_length=12)
    social_captions: SocialCaptions


class MiloSettings(Contract):
    daily_enabled: bool = True
    spike_enabled: bool = True
    daily_hour: StrictInt = Field(default=9, ge=0, le=23)
    timezone: str = 'Asia/Tashkent'
    spike_threshold: StrictInt = Field(default=5, ge=1, le=1000)
    window_days: StrictInt = Field(default=7, ge=1, le=365)
    cooldown_hours: StrictInt = Field(default=24, ge=1, le=720)

    @model_validator(mode='after')
    def valid_timezone(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Invalid scheduling timezone') from None
        return self


class BrandConfig(Contract):
    campaign_language: Literal['en', 'ru', 'uz'] = 'en'
    personas: list[Persona] = Field(default_factory=list, max_length=20)
    proof_points: list[ProofPoint] = Field(default_factory=list, max_length=100)
    banned_terms: list[str] = Field(default_factory=list, max_length=100)
    competitor_names: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def unique_ids(self):
        for records in (self.personas, self.proof_points):
            if len({item.id for item in records}) != len(records):
                raise ValueError('Persona and proof identifiers must be unique')
        if any(not term.strip() or len(term) > 200 for term in self.banned_terms + self.competitor_names):
            raise ValueError('Terms must be nonempty and at most 200 characters')
        if any(set(point.objection_topics) - set(TOPICS) for point in self.proof_points):
            raise ValueError('Unknown objection topic')
        return self
