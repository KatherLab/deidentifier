"""Independent leakage validation of the anonymized output.

This pass never edits the output; it only produces warnings for the user.
Warning offsets refer to the anonymized output text.
"""

import re

from ..schemas.entities import (
    AppliedEntity,
    EntityType,
    SpanStatus,
    TransformationType,
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
    ValidationWarning,
)
from .policy import DEFAULT_POLICY
from .rules import RuleBasedDetector

# Trivially short strings ("12", "80") re-occur legitimately; checking them
# for residuals would flood the result with false alarms.
_MIN_RESIDUAL_LENGTH = 4

# "Patient: Something" where Something is not a replacement tag.
_LABELLED_FIELD = re.compile(
    r"(?:Patient(?:in)?|Name|Anschrift|Adresse|Wohnhaft)\s*:\s*(?!\[)([A-ZÄÖÜ][^\n]{2,40})"
)


async def validate_output(
    anonymized: str,
    applied: list[AppliedEntity],
    policy: dict[EntityType, TransformationType] | None = None,
    detector_warnings: list[str] | None = None,
) -> ValidationResult:
    active_policy = policy if policy is not None else DEFAULT_POLICY
    warnings: list[ValidationWarning] = []

    # 0. Detector problems (e.g. an LLM mention that could not be grounded)
    # mean the document may contain unredacted PII — the result must never
    # claim PASS in that case.
    for message in detector_warnings or []:
        warnings.append(
            ValidationWarning(
                category="detector",
                message=message,
                severity=ValidationSeverity.WARNING,
            )
        )

    # 1. Redacted content must not remain anywhere in the output.
    for entity in applied:
        if entity.status == SpanStatus.PRESERVED:
            continue
        needle = entity.text.strip()
        if len(needle) < _MIN_RESIDUAL_LENGTH:
            continue
        index = anonymized.find(needle)
        if index != -1:
            warnings.append(
                ValidationWarning(
                    category="residual_identifier",
                    message=f"Redacted {entity.entity_type} content appears to remain in the output.",
                    severity=ValidationSeverity.HIGH,
                    start=index,
                    end=index + len(needle),
                )
            )

    # 2. Re-run the rule detectors on the output.
    preserved_texts = {e.text for e in applied if e.status == SpanStatus.PRESERVED}
    for span in (await RuleBasedDetector().detect(anonymized)).spans:
        if active_policy.get(span.entity_type) == TransformationType.PRESERVE:
            continue
        if span.text in preserved_texts:
            continue
        warnings.append(
            ValidationWarning(
                category="revalidation_hit",
                message=f"A rule detector still finds a possible {span.entity_type} in the output.",
                severity=ValidationSeverity.WARNING,
                start=span.start,
                end=span.end,
            )
        )

    # 3. Suspicious labelled fields followed by non-redacted content.
    for match in _LABELLED_FIELD.finditer(anonymized):
        start, end = match.span(1)
        warnings.append(
            ValidationWarning(
                category="labelled_field",
                message="A labelled field appears to be followed by non-redacted content.",
                severity=ValidationSeverity.WARNING,
                start=start,
                end=end,
            )
        )

    return ValidationResult(status=compute_status(warnings), warnings=warnings)


def compute_status(warnings: list[ValidationWarning]) -> ValidationStatus:
    """HIGH → FAIL, WARNING → REVIEW_REQUIRED; INFO alone still passes."""
    if any(w.severity == ValidationSeverity.HIGH for w in warnings):
        return ValidationStatus.FAIL
    if any(w.severity == ValidationSeverity.WARNING for w in warnings):
        return ValidationStatus.REVIEW_REQUIRED
    return ValidationStatus.PASS
