"""Request/response schemas for the anonymization and status endpoints."""

from pydantic import BaseModel, Field, model_validator

from .entities import (
    AppliedEntity,
    EntityType,
    Notice,
    OutputLanguage,
    TransformationType,
    ValidationResult,
)


class EntityOverride(BaseModel):
    """A per-span user decision from the review UI. Matched against detected
    spans by (start, end, text); overrides beat every policy rule."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    transformation: TransformationType | None = None
    entity_type: EntityType | None = None


class RedactArea(BaseModel):
    """A user-drawn blackout region on a PDF page (review UI). Coordinates are
    normalized to 0–1000 of the page width/height with a TOP-LEFT origin
    (matching LayoutLine). Applied at PDF export only — the text outputs are
    unaffected."""

    page: int = Field(ge=1)
    x0: float = Field(ge=0, le=1000)
    y0: float = Field(ge=0, le=1000)
    x1: float = Field(ge=0, le=1000)
    y1: float = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def _non_empty(self) -> "RedactArea":
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("area must have positive width and height")
        return self


class PageImageBox(BaseModel):
    """Bounding box of an embedded image on a rendered page (normalized
    0–1000, top-left origin) — offered as one-click redaction suggestions."""

    x0: float
    y0: float
    x1: float
    y1: float


class PageRender(BaseModel):
    """One rendered PDF page for the area-redaction editor."""

    page: int
    # Page size in PDF points (for aspect ratio; coordinates stay normalized).
    width: float
    height: float
    # PNG data URL of the rendered page.
    image: str
    image_boxes: list[PageImageBox]


class PdfPagesResponse(BaseModel):
    pages: list[PageRender]
    # True when the document has more pages than the render cap.
    truncated: bool


class AnonymizeTextRequest(BaseModel):
    """Either fresh text, or a request_id referencing cached detection results
    (for cheap re-runs after review-UI overrides)."""

    text: str | None = Field(default=None, min_length=1)
    request_id: str | None = None
    overrides: list[EntityOverride] = Field(default_factory=list)
    # Partial per-type policy from the UI's advanced settings; overlays the
    # default policy. Sent with every request (stateless, like overrides).
    policy: dict[EntityType, TransformationType] | None = None
    # Custom rules (advanced settings). redact_terms and custom_instruction
    # affect detection and only apply to fresh runs; preserve_terms applies at
    # transformation time and is honored on re-runs too.
    custom_instruction: str | None = Field(default=None, max_length=2000)
    redact_terms: list[str] = Field(default_factory=list, max_length=100)
    preserve_terms: list[str] = Field(default_factory=list, max_length=100)
    # Language of the replacement placeholders (and of the re-check's notes).
    # Sent with every request of a run, including override re-runs, so an
    # adjusted document keeps the placeholders it already shows. Omitted =
    # German; a cached re-run keeps the original run's language.
    output_language: OutputLanguage | None = None

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
    # The language its placeholders are written in (fixed at submit).
    output_language: OutputLanguage
    source_text: str
    anonymized_text: str
    entities: list[AppliedEntity]
    validation: ValidationResult
    # Non-fatal notices about the run (extraction hints, ignored overrides).
    # Each carries a stable `code` the UI translates, plus English `message`.
    warnings: list[Notice] = Field(default_factory=list)
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
