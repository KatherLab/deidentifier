"""Deterministic transformations.

Pure functions only: the source text is never mutated; replacements are applied
right-to-left on a copy so earlier offsets stay valid.
"""

import re

from ..schemas.anonymize import EntityOverride
from ..schemas.entities import (
    AppliedEntity,
    EntitySpan,
    EntityType,
    SpanStatus,
    TransformationType,
)
from .policy import DEFAULT_POLICY, REDACTED_LABEL, TYPE_MASK_LABELS

_WHITESPACE = re.compile(r"\s+")
_YEAR = re.compile(r"(?:19|20)\d{2}")


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()


def apply_policy(
    text: str,
    spans: list[EntitySpan],
    policy: dict[EntityType, TransformationType] | None = None,
    overrides: list[EntityOverride] | None = None,
) -> tuple[str, list[AppliedEntity], list[str]]:
    """Return (anonymized text, applied entities with source offsets, warnings).

    Overrides are matched by (start, end, text) and beat the policy; unmatched
    overrides produce warnings instead of being silently dropped.
    """
    active_policy = policy if policy is not None else DEFAULT_POLICY
    override_map: dict[tuple[int, int], EntityOverride] = {
        (o.start, o.end): o for o in (overrides or [])
    }
    matched_overrides: set[tuple[int, int]] = set()

    # Consistent tags are numbered by first appearance of the normalized value.
    tag_numbers: dict[str, int] = {}
    applied: list[AppliedEntity] = []

    for span in sorted(spans, key=lambda s: s.start):
        override = override_map.get((span.start, span.end))
        if override is not None and override.text == span.text:
            matched_overrides.add((span.start, span.end))
            if override.entity_type is not None:
                span = span.model_copy(update={"entity_type": override.entity_type})
            span = span.model_copy(update={"metadata": {**span.metadata, "overridden": True}})
            transformation = override.transformation or active_policy.get(
                span.entity_type, TransformationType.TYPE_MASK
            )
        else:
            transformation = active_policy.get(span.entity_type, TransformationType.TYPE_MASK)
        replacement: str | None
        if transformation == TransformationType.CONSISTENT_TAG:
            # tag_group (set by LLM grounding) links title variants and name
            # parts of the same person to one tag; fall back to the text.
            key = str(span.metadata.get("tag_group") or _normalize(span.text))
            if key not in tag_numbers:
                tag_numbers[key] = len(tag_numbers) + 1
            replacement = f"[PERSON_{tag_numbers[key]}]"
            status = SpanStatus.TAGGED
        elif transformation == TransformationType.GENERALIZE:
            match = _YEAR.search(span.text)
            replacement = match.group(0) if match else TYPE_MASK_LABELS[span.entity_type]
            status = SpanStatus.GENERALIZED
        elif transformation == TransformationType.REMOVE:
            replacement = REDACTED_LABEL
            status = SpanStatus.REDACTED
        elif transformation == TransformationType.PRESERVE:
            replacement = None
            status = SpanStatus.PRESERVED
        else:
            replacement = TYPE_MASK_LABELS[span.entity_type]
            status = SpanStatus.REDACTED
        applied.append(
            AppliedEntity(
                **span.model_dump(),
                transformation=transformation,
                replacement=replacement,
                status=status,
            )
        )

    warnings = [
        "An override did not match any detected span and was ignored."
        for key in override_map
        if key not in matched_overrides
    ]

    result = text
    for entity in sorted(applied, key=lambda e: e.start, reverse=True):
        if entity.replacement is None:
            continue
        result = result[: entity.start] + entity.replacement + result[entity.end :]
    return result, applied, warnings
