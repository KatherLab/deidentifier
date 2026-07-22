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


class ValidationWarning(BaseModel):
    category: str
    message: str
    severity: ValidationSeverity
    # Offsets refer to the anonymized output, not the source.
    start: int | None = None
    end: int | None = None


class ValidationResult(BaseModel):
    status: ValidationStatus
    warnings: list[ValidationWarning] = Field(default_factory=list)
