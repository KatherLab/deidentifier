"""Request/response schemas for the anonymization and status endpoints."""

from pydantic import BaseModel, Field, model_validator

from .entities import AppliedEntity, EntityType, TransformationType, ValidationResult


class EntityOverride(BaseModel):
    """A per-span user decision from the review UI. Matched against detected
    spans by (start, end, text); overrides beat every policy rule."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    transformation: TransformationType | None = None
    entity_type: EntityType | None = None


class AnonymizeTextRequest(BaseModel):
    """Either fresh text, or a request_id referencing cached detection results
    (for cheap re-runs after review-UI overrides)."""

    text: str | None = Field(default=None, min_length=1)
    request_id: str | None = None
    overrides: list[EntityOverride] = Field(default_factory=list)
    # Partial per-type policy from the UI's advanced settings; overlays the
    # default policy. Sent with every request (stateless, like overrides).
    policy: dict[EntityType, TransformationType] | None = None

    @model_validator(mode="after")
    def _text_or_request_id(self) -> "AnonymizeTextRequest":
        if self.text is None and self.request_id is None:
            raise ValueError("either 'text' or 'request_id' is required")
        return self


class TimingMs(BaseModel):
    extraction: float
    detection: float
    transformation: float
    validation: float
    total: float


class AnonymizeResponse(BaseModel):
    request_id: str
    source_type: str
    source_text: str
    anonymized_text: str
    entities: list[AppliedEntity]
    validation: ValidationResult
    warnings: list[str] = Field(default_factory=list)
    timing_ms: TimingMs


class DetectorStatus(BaseModel):
    name: str
    enabled: bool
    ready: bool


class ExternalEndpoint(BaseModel):
    name: str
    host: str
    local: bool


class Limits(BaseModel):
    max_upload_mb: int
    max_text_chars: int


class StatusResponse(BaseModel):
    app_env: str
    version: str
    detectors: list[DetectorStatus]
    ocr_engine: str
    external_endpoints: list[ExternalEndpoint]
    limits: Limits
