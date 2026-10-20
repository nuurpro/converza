"""Versioned media artifact contract. Paths and manifests stay server-side."""
from typing import Any, Literal
from pydantic import Field, StrictInt, field_validator
from services.milo.contracts import Contract

PRESETS = ('high_velocity_d2c', 'editorial_showcase')


class VeaVideoArtifact(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1)
    variant_revision: StrictInt = Field(ge=1)
    video_url: str = Field(min_length=1)
    thumbnail_url: str = Field(min_length=1)
    duration_sec: float = Field(gt=0)
    preset_used: Literal['high_velocity_d2c', 'editorial_showcase']
    preset_version: StrictInt = Field(ge=1)
    preset_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_milo_script_id: str = Field(min_length=1)
    approved_script_revision: StrictInt = Field(ge=1)
    composition_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    render_telemetry: dict[str, Any]

    @field_validator('video_url', 'thumbnail_url')
    @classmethod
    def public_media(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Media URL must be an HTTP URL without credentials')
        return value


class VariantRequest(Contract):
    campaign_id: str = Field(min_length=1, max_length=100)
    expected_revision: StrictInt = Field(ge=1)
    preset_id: Literal['high_velocity_d2c', 'editorial_showcase'] = 'high_velocity_d2c'


class RevisionRequest(Contract):
    expected_revision: StrictInt = Field(ge=1)


class SwapRequest(RevisionRequest):
    segment_id: str = Field(min_length=1, max_length=200)
    asset_id: str = Field(min_length=1, max_length=200)
