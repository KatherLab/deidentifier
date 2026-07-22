"""Detector protocol, shared detection types, mock detector, and registry."""

from typing import Protocol

from ..core.config import Settings
from ..schemas.entities import EntitySpan, EntityType


class DetectionOutcome:
    """Spans plus non-fatal warnings from one detector run."""

    def __init__(self, spans: list[EntitySpan], warnings: list[str] | None = None):
        self.spans = spans
        self.warnings = warnings or []


class DetectorError(Exception):
    """A configured detector cannot run; the request must fail (recall-first:
    never silently degrade to fewer detectors)."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class SpanDetector(Protocol):
    name: str
    version: str

    async def detect(self, text: str) -> DetectionOutcome: ...


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


def detector_ready(name: str, settings: Settings) -> bool:
    """Whether a configured detector can actually run right now."""
    if name in {"rules", "mock"}:
        return True
    if name == "llm":
        return bool(settings.OPENAI_API_BASE and settings.LLM_MODEL)
    return False  # privacy_filter arrives in Milestone 3


def build_detectors(settings: Settings) -> list[SpanDetector]:
    """Instantiate configured detectors.

    Raises DetectorError for detectors that are enabled but cannot run —
    silently proceeding with fewer detectors would report a document as
    anonymized when it was not fully checked.
    """
    from .llm_detection import LLMDetector
    from .rules import RuleBasedDetector

    detectors: list[SpanDetector] = []
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
            detectors.append(LLMDetector(settings))
        else:
            raise DetectorError(
                f"Detector '{name}' is not available in this build; "
                "the document was NOT anonymized.",
                status_code=503,
            )
    return detectors


def validate_spans(text: str, spans: list[EntitySpan]) -> tuple[list[EntitySpan], list[str]]:
    """Reject any span whose text does not match its offsets in the source."""
    valid: list[EntitySpan] = []
    warnings: list[str] = []
    for span in spans:
        if span.end <= len(text) and text[span.start : span.end] == span.text:
            valid.append(span)
        else:
            warnings.append(
                f"Rejected invalid span from detector '{span.detector}' (offset mismatch)."
            )
    return valid, warnings
