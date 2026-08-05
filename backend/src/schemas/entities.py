"""Canonical entity schema shared by all detectors and transformations."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class EntityType(StrEnum):
    PERSON_NAME = "PERSON_NAME"  # any person; role (patient/clinician/…) in metadata
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    OTHER_DATE = "OTHER_DATE"
    AGE = "AGE"
    ADDRESS = "ADDRESS"  # street / postal code / city
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    URL = "URL"
    ID_NUMBER = "ID_NUMBER"  # patient/case/insurance/accession IDs, IBANs
    ORGANIZATION = "ORGANIZATION"  # hospital, practice, employer, school
    PROFESSION = "PROFESSION"
    OTHER_PII = "OTHER_PII"


class TransformationType(StrEnum):
    TYPE_MASK = "TYPE_MASK"
    CONSISTENT_TAG = "CONSISTENT_TAG"
    GENERALIZE = "GENERALIZE"
    REMOVE = "REMOVE"
    PRESERVE = "PRESERVE"


class OutputLanguage(StrEnum):
    """Language of everything a run WRITES into the document: the replacement
    placeholders and the free-text notes of the LLM re-check.

    Chosen per request (the UI captures it at submit) and independent of the
    language the interface happens to be showing — the placeholders of a
    finished document must not change when the reviewer switches language.
    """

    DE = "de"
    EN = "en"
    FR = "fr"
    ES = "es"


class SpanStatus(StrEnum):
    REDACTED = "REDACTED"
    GENERALIZED = "GENERALIZED"
    TAGGED = "TAGGED"
    PRESERVED = "PRESERVED"


class EntitySpan(BaseModel):
    """A detected sensitive span. Offsets are Unicode code points into the
    immutable source text; `text` must equal `source[start:end]`."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    entity_type: EntityType
    confidence: float = Field(ge=0, le=1)
    detector: str
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_span(self) -> "EntitySpan":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if len(self.text) != self.end - self.start:
            raise ValueError("span text length does not match offsets")
        return self


class AppliedEntity(EntitySpan):
    """An entity after policy application; replacement is None for PRESERVE."""

    transformation: TransformationType
    replacement: str | None
    status: SpanStatus


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"


class ValidationStatus(StrEnum):
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAIL = "FAIL"


class Notice(BaseModel):
    """A translatable, non-fatal message about a run (extraction hints, ignored
    overrides, …).

    `code` is a stable identifier the frontend maps to a localized string;
    `params` carries its placeholders. `message` is the English rendering and
    stays the fallback for any code a catalog does not know — a notice is never
    only a code, so an API consumer always has readable text.
    """

    code: str
    message: str
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ValidationWarning(BaseModel):
    category: str
    message: str
    severity: ValidationSeverity
    # Offsets refer to the anonymized output, not the source.
    start: int | None = None
    end: int | None = None
    # Translation contract, as for Notice. Empty for warnings whose text comes
    # from the model itself (LLM re-check concerns) — those stay as `message`.
    code: str = ""
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    status: ValidationStatus
    warnings: list[ValidationWarning] = Field(default_factory=list)
