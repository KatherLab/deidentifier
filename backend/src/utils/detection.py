"""Detector protocol, shared detection types, mock detector, and registry."""

import re

from ..core.config import Settings
from ..schemas.entities import EntitySpan, EntityType, Notice
from .detector_base import DetectionOutcome, DetectorError, SpanDetector
from .llm_detection import LLMDetector
from .notices import INVALID_SPAN_REJECTED, notice
from .rules import RuleBasedDetector

__all__ = [
    "DetectionOutcome",
    "DetectorError",
    "MockDetector",
    "SpanDetector",
    "TermListDetector",
    "build_detectors",
    "detector_ready",
    "validate_spans",
]

# Fixture values recognized by the mock detector (tests/offline development only).
MOCK_FIXTURES: dict[str, EntityType] = {
    "Max Mustermann": EntityType.PERSON_NAME,
    "Erika Musterfrau": EntityType.PERSON_NAME,
    "Musterstraße 12": EntityType.ADDRESS,
    "01307 Dresden": EntityType.ADDRESS,
    "01.02.1980": EntityType.DATE_OF_BIRTH,
    "PAT-123456": EntityType.ID_NUMBER,
}


class MockDetector:
    name = "mock"
    version = "1.0"

    async def detect(self, text: str) -> DetectionOutcome:
        spans: list[EntitySpan] = []
        for fixture, entity_type in MOCK_FIXTURES.items():
            start = text.find(fixture)
            while start != -1:
                spans.append(
                    EntitySpan(
                        start=start,
                        end=start + len(fixture),
                        text=fixture,
                        entity_type=entity_type,
                        confidence=1.0,
                        detector=self.name,
                    )
                )
                start = text.find(fixture, start + 1)
        return DetectionOutcome(spans=spans)


class TermListDetector:
    """Deterministic always-redact terms from the user's custom rules.

    Word-bounded, case-insensitive matching of every occurrence; entirely
    independent of the LLM, so user-critical terms never depend on model
    behavior."""

    name = "user_terms"
    version = "1.0"

    def __init__(self, terms: list[str]):
        self._patterns = [
            re.compile(rf"(?<!\w){re.escape(term.strip())}(?!\w)", re.IGNORECASE)
            for term in terms
            if term.strip()
        ]

    async def detect(self, text: str) -> DetectionOutcome:
        spans: list[EntitySpan] = []
        seen: set[tuple[int, int]] = set()
        for pattern in self._patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                if (start, end) in seen:
                    continue
                seen.add((start, end))
                spans.append(
                    EntitySpan(
                        start=start,
                        end=end,
                        text=text[start:end],
                        entity_type=EntityType.OTHER_PII,
                        confidence=1.0,
                        detector=self.name,
                        metadata={"user_term": True},
                    )
                )
        return DetectionOutcome(spans=spans)


def detector_ready(name: str, settings: Settings) -> bool:
    """Whether a configured detector can actually run right now."""
    if name in {"rules", "mock"}:
        return True
    if name == "llm":
        return bool(settings.OPENAI_API_BASE and settings.LLM_MODEL)
    return False  # an unknown name is never ready; build_detectors rejects it


def build_detectors(
    settings: Settings,
    custom_instruction: str | None = None,
    redact_terms: list[str] | None = None,
    progress=None,
) -> list[SpanDetector]:
    """Instantiate configured detectors.

    Raises DetectorError for detectors that are enabled but cannot run —
    silently proceeding with fewer detectors would report a document as
    anonymized when it was not fully checked.
    """
    detectors: list[SpanDetector] = []
    if redact_terms:
        detectors.append(TermListDetector(redact_terms))
    for name in settings.detector_names:
        if name == "rules":
            detectors.append(RuleBasedDetector())
        elif name == "mock":
            detectors.append(MockDetector())
        elif name == "llm":
            if not detector_ready("llm", settings):
                raise DetectorError(
                    "Detector 'llm' is enabled but OPENAI_API_BASE/LLM_MODEL are not "
                    "configured; the document was NOT anonymized.",
                    status_code=503,
                )
            detectors.append(
                LLMDetector(settings, custom_instruction=custom_instruction, progress=progress)
            )
        else:
            raise DetectorError(
                f"Detector '{name}' is not available in this build; "
                "the document was NOT anonymized.",
                status_code=503,
            )
    return detectors


def validate_spans(text: str, spans: list[EntitySpan]) -> tuple[list[EntitySpan], list[Notice]]:
    """Reject any span whose text does not match its offsets in the source."""
    valid: list[EntitySpan] = []
    warnings: list[Notice] = []
    for span in spans:
        if span.end <= len(text) and text[span.start : span.end] == span.text:
            valid.append(span)
        else:
            warnings.append(notice(INVALID_SPAN_REJECTED, detector=span.detector))
    return valid, warnings
