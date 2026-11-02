"""Versioned, strict Milo–Vea director boundary."""
from typing import Literal
from pydantic import ConfigDict,Field, StrictInt, model_validator
from services.milo.contracts import Contract as MiloContract


class Contract(MiloContract):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,strict=True)

SHA = r'^[a-f0-9]{64}$'


class VisualDirective(Contract):
    prompt: str = Field(min_length=1,max_length=4000)
    subject_action: str = Field(min_length=1,max_length=1000)
    camera_movement: str = Field(min_length=1,max_length=500)
    lighting_style: str = Field(min_length=1,max_length=500)


class AssetConstraints(Contract):
    required_sku_tags: list[str] = Field(default_factory=list,max_length=30)
    brand_hex_palette: list[str] = Field(default_factory=list,max_length=12)
    negative_visual_constraints: list[str] = Field(default_factory=list,max_length=100)

    @model_validator(mode='after')
    def colors(self):
        import re
        if any(not re.fullmatch(r'#[a-fA-F0-9]{6}',v) for v in self.brand_hex_palette):
            raise ValueError('Brand palette requires six-digit hex colors')
        if any(not value.strip() for value in self.required_sku_tags+self.negative_visual_constraints):
            raise ValueError('Asset constraints cannot contain blank values')
        return self


class OverlayText(Contract):
    text: str = Field(max_length=500)
    font_family: str = Field(default='DejaVuSans',min_length=1,max_length=100,pattern=r'^[\w .-]+$')
    font_size: StrictInt = Field(default=54,ge=16,le=160)
    color: str = Field(default='#FFFFFF',pattern=r'^#[a-fA-F0-9]{6}$')
    position: Literal['top','center','bottom'] = 'center'
    animation: Literal['none','fade','slide'] = 'none'
    start_sec: float = Field(default=0,ge=0)
    end_sec: float = Field(gt=0)


class ScenePromptPayload(Contract):
    scene_index: StrictInt = Field(ge=1,le=12)
    total_scenes: StrictInt = Field(ge=1,le=12)
    target_duration_sec: float = Field(gt=0,le=120)
    narration_chunk: str = Field(min_length=1,max_length=1500,pattern=r'\S')
    visual_directive: VisualDirective
    asset_constraints: AssetConstraints
    overlay_text: OverlayText

    @model_validator(mode='after')
    def bounds(self):
        if self.scene_index>self.total_scenes: raise ValueError('Scene index exceeds total')
        if not 0<=self.overlay_text.start_sec<self.overlay_text.end_sec<=self.target_duration_sec:
            raise ValueError('Overlay interval must fit the scene')
        return self


class Storyboard(Contract):
    revision: StrictInt = Field(ge=1)
    scenes: list[ScenePromptPayload] = Field(min_length=1,max_length=12)
    narration_approved: bool = False

    @model_validator(mode='after')
    def order(self):
        if [s.scene_index for s in self.scenes]!=list(range(1,len(self.scenes)+1)) or any(s.total_scenes!=len(self.scenes) for s in self.scenes):
            raise ValueError('Storyboard scenes must be complete and ordered')
        return self


class SceneVerificationResult(Contract):
    schema_version: Literal[1] = 1
    scene_index: StrictInt = Field(ge=1,le=12)
    spec_sha256: str = Field(pattern=SHA)
    artifact_sha256: str = Field(pattern=SHA)
    attempt: StrictInt = Field(ge=1,le=3)
    passed: bool
    media_passed: bool
    alignment_passed: bool
    ocr_passed: bool
    provenance_passed: bool
    violations: list[str]
    correction_notes: list[str]
    measured_video_duration_sec: float | None = Field(default=None,ge=0)
    measured_audio_duration_sec: float | None = Field(default=None,ge=0)
    alignment_score: float | None = Field(default=None,ge=0,le=1)
    anchor_coverage: float | None = Field(default=None,ge=0,le=1)
    observed_transcript: str = ''
    ocr_observations: list[str] = Field(default_factory=list)
    provenance_asset_ids: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def verdict(self):
        checks=all((self.media_passed,self.alignment_passed,self.ocr_passed,self.provenance_passed))
        if self.passed != (checks and not self.violations): raise ValueError('Verification verdict contradicts evidence')
        return self


class VerifiedSceneToken(Contract):
    scene_index: StrictInt = Field(ge=1,le=12)
    task_id: str = Field(min_length=1,max_length=200)
    artifact_sha256: str = Field(pattern=SHA)
    verified_token: str = Field(min_length=1,max_length=200)


class MasterAssemblyManifest(Contract):
    schema_version: Literal[1] = 1
    storyboard_revision: StrictInt = Field(ge=1)
    scenes: list[VerifiedSceneToken] = Field(min_length=1,max_length=12)
    target_duration_sec: float = Field(gt=0,le=1440)
    transitions: list[Literal['cut','crossfade']] = Field(default_factory=list,max_length=11)
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    format: Literal['mp4'] = 'mp4'
    audio_ducking_db: float = Field(default=-18,le=-12,ge=-60)
    background_asset_id: str | None = Field(default=None,min_length=1,max_length=200)

    @model_validator(mode='after')
    def complete(self):
        if [s.scene_index for s in self.scenes]!=list(range(1,len(self.scenes)+1)):
            raise ValueError('Assembly tokens must be ordered and complete')
        if len({s.task_id for s in self.scenes})!=len(self.scenes): raise ValueError('Duplicate scene task')
        if self.transitions and len(self.transitions)!=len(self.scenes)-1: raise ValueError('One transition per scene boundary')
        return self
