"""The detector contract: protocol, outcome type, and failure exception.

Kept separate from `detection.py` so concrete detectors (`rules.py`,
`llm_detection.py`) can depend on the contract while `detection.py` — the
registry that instantiates them — depends on the detectors. Merging the two
would make that a cycle.
"""

from typing import Protocol

from ..schemas.entities import EntitySpan, Notice


class DetectionOutcome:
    """Spans plus non-fatal warnings from one detector run."""

    def __init__(self, spans: list[EntitySpan], warnings: list[Notice] | None = None):
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

    async def detect(self, text: str) -> DetectionOutcome:
        """Propose entity spans over the unmodified source text."""
