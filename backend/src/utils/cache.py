"""Short-lived in-memory cache of detection results, keyed by request ID.

Purpose: when the user adjusts individual entities in the review UI, the
deterministic transformation can be re-run without repeating (expensive) LLM
detection. Nothing is persisted; entries expire after a TTL and the cache is
bounded. This is the only place where document text lives between requests,
and it exists only in process memory.

Lifetime rules — these are retention guarantees, not tuning knobs. The three
durations are operator-configurable (`RESULT_CACHE_*`, see `.env.example`);
their *relationship* is not:

- An entry expires `ttl` after it was created — short by default, because most
  results are reviewed and exported within minutes. **Reading it never extends
  that window**, or a long review session would keep a document resident for as
  long as someone kept clicking.
- A reviewer who needs longer can `extend()` — an explicit, visible act, offered
  by the UI at any time. It moves the deadline to `extension` from *now*, and is
  repeatable: someone working through a stack of documents keeps them all
  available without ever pausing to think about a cache.
- No entry outlives `max_lifetime` after its creation, however often it is
  extended. That ceiling is the retention promise in `docs/DATA_RETENTION.md`;
  it is what makes "this document is gone by the end of the day" true no matter
  how the UI behaves or how long a tab stays open.
- `sweep()` runs on every access *and* on a timer from the app's lifespan task,
  so an idle process does not hold the last documents it saw; `clear()` runs on
  shutdown.
"""

import time
from dataclasses import dataclass, field

from ..schemas.entities import EntitySpan, Notice, OutputLanguage
from .extraction import LayoutLine

#: Defaults, mirrored by the `RESULT_CACHE_*` settings. Used until the app's
#: lifespan configures the singleton — and by tests, which construct their own.
DEFAULT_TTL_SECONDS = 15 * 60.0
DEFAULT_EXTENSION_SECONDS = 60 * 60.0
DEFAULT_MAX_LIFETIME_SECONDS = 12 * 60 * 60.0


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
    #: Monotonic creation time — the anchor of the hard lifetime ceiling.
    created_at: float = 0.0
    #: Monotonic time this entry dies; moved forward only by `extend()`.
    expires_at: float = 0.0


class RequestCache:
    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = 100,
        max_lifetime_seconds: float = DEFAULT_MAX_LIFETIME_SECONDS,
        extension_seconds: float = DEFAULT_EXTENSION_SECONDS,
    ):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._max_lifetime = max_lifetime_seconds
        self._extension = extension_seconds
        self._entries: dict[str, CachedDetection] = {}

    def configure(self, settings) -> None:
        """Adopt the operator's `RESULT_CACHE_*` settings (called once, from the
        app's lifespan). Existing entries keep the deadlines they were given —
        a reconfiguration mid-flight must not silently lengthen the retention
        of a document already in memory."""
        self._ttl = settings.RESULT_CACHE_TTL_MINUTES * 60.0
        self._extension = settings.RESULT_CACHE_EXTENSION_MINUTES * 60.0
        self._max_lifetime = settings.RESULT_CACHE_MAX_LIFETIME_MINUTES * 60.0
        self._max = settings.RESULT_CACHE_MAX_ENTRIES
        # A tightened bound applies to what is already here, not just to the
        # next result: restricting retention must take effect immediately.
        self.sweep()
        self._enforce_bound()

    def put(self, request_id: str, entry: CachedDetection) -> None:
        self.sweep()
        now = time.monotonic()
        entry.created_at = now
        # The ceiling binds the first window too, so a max_lifetime configured
        # below the TTL shortens retention rather than being ignored.
        entry.expires_at = now + min(self._ttl, self._max_lifetime)
        self._entries[request_id] = entry
        self._enforce_bound()

    def _enforce_bound(self) -> None:
        """Over the bound: the oldest document goes first, so the cache never
        holds more than `max_entries` and never the longest-resident text."""
        while len(self._entries) > self._max:
            oldest = min(self._entries, key=lambda k: self._entries[k].created_at)
            del self._entries[oldest]

    def get(self, request_id: str) -> CachedDetection | None:
        self.sweep()
        return self._entries.get(request_id)

    def discard(self, request_id: str) -> None:
        """Forget one entry now (the user closed or reset the document)."""
        self._entries.pop(request_id, None)

    def clear(self) -> None:
        """Drop everything (shutdown)."""
        self._entries.clear()

    def sweep(self) -> int:
        """Delete every entry that has reached its expiry; returns how many.

        Called on each access *and* periodically from the lifespan task — an
        idle process must not keep the documents it last saw.
        """
        now = time.monotonic()
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]
        return len(expired)

    def lifetime(self, request_id: str) -> tuple[int, bool] | None:
        """`(seconds until this entry expires, whether it may still be
        extended)`, or None when there is no such entry. The UI counts down
        from this."""
        entry = self.get(request_id)
        if entry is None:
            return None
        return self._lifetime_of(entry, time.monotonic())

    def extend(self, request_id: str) -> tuple[int, bool] | None:
        """Move the deadline to `extension` from now, up to the hard ceiling.

        Repeatable: each press buys the reviewer a fresh full window, so a long
        review never turns into a race against a countdown. `max(...)` keeps a
        press from ever *shortening* a deadline.

        Returns the same pair as `lifetime()`, or None when the entry is gone —
        the caller answers 410 and the browser re-sends the source text. At the
        ceiling this is a no-op reporting `can_extend=False`, so the UI can say
        "cannot be extended further" instead of pretending the click worked.
        """
        entry = self.get(request_id)
        if entry is None:
            return None
        now = time.monotonic()
        ceiling = entry.created_at + self._max_lifetime
        entry.expires_at = max(entry.expires_at, min(now + self._extension, ceiling))
        return self._lifetime_of(entry, now)

    def _lifetime_of(self, entry: CachedDetection, now: float) -> tuple[int, bool]:
        """`can_extend` asks whether the entry has headroom left before its
        ceiling — not whether a click *this second* would add time. Right after
        an extension the latter is briefly false, which would make the button
        flicker for no reason a reviewer could understand."""
        remaining = max(0, int(entry.expires_at - now))
        return remaining, entry.expires_at < entry.created_at + self._max_lifetime


request_cache = RequestCache()
