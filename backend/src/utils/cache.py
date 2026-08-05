"""Short-lived in-memory cache of detection results, keyed by request ID.

Purpose: when the user adjusts individual entities in the review UI, the
deterministic transformation can be re-run without repeating (expensive) LLM
detection. Nothing is persisted; entries expire after a TTL and the cache is
bounded. This is the only place where document text lives between requests,
and it exists only in process memory.
"""

import time
from dataclasses import dataclass, field

from ..schemas.entities import EntitySpan, Notice, OutputLanguage
from .extraction import LayoutLine


@dataclass
class CachedDetection:
    text: str
    source_type: str
    spans: list[EntitySpan]
    extraction_warnings: list[Notice]
    detection_warnings: list[Notice] = field(default_factory=list)
    llm_recheck_performed: bool = False
    # Output language of the original run: an override re-run that omits it
    # keeps the placeholders of the document the user is already reviewing.
    output_language: OutputLanguage | None = None
    # For redacted-PDF export: identity of the uploaded file plus (for scans)
    # the OCR layout, so an export never repeats OCR/LLM detection.
    file_sha256: str | None = None
    layout: list[LayoutLine] = field(default_factory=list)
    page_count: int = 0
    timestamp: float = 0.0


class RequestCache:
    def __init__(self, ttl_seconds: float = 900.0, max_entries: int = 100):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._entries: dict[str, CachedDetection] = {}

    def put(self, request_id: str, entry: CachedDetection) -> None:
        self._evict()
        entry.timestamp = time.monotonic()
        self._entries[request_id] = entry
        while len(self._entries) > self._max:
            oldest = min(self._entries, key=lambda k: self._entries[k].timestamp)
            del self._entries[oldest]

    def get(self, request_id: str) -> CachedDetection | None:
        self._evict()
        entry = self._entries.get(request_id)
        if entry is not None:
            entry.timestamp = time.monotonic()
        return entry

    def _evict(self) -> None:
        cutoff = time.monotonic() - self._ttl
        expired = [key for key, entry in self._entries.items() if entry.timestamp < cutoff]
        for key in expired:
            del self._entries[key]


request_cache = RequestCache()
