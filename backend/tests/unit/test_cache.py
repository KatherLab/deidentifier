"""The detection cache is the only place document text lives between requests,
so its retention behavior is a security property, not an implementation detail:
an absolute maximum age, a hard bound, and no way to keep an entry alive by
touching it."""

from backend.src.utils.cache import CachedDetection, RequestCache


def entry(text: str = "Patient Hans Mueller") -> CachedDetection:
    return CachedDetection(text=text, source_type="paste", spans=[], extraction_warnings=[])


def test_reading_an_entry_does_not_extend_its_life(monkeypatch):
    """A long review session must not keep a document resident forever."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=900.0)
    cache.put("a", entry())

    now = 1800.0  # 13 minutes in, still cached — and read repeatedly
    assert cache.get("a") is not None
    assert cache.get("a") is not None

    now = 1901.0  # 15 minutes after it was CREATED, not after the last read
    assert cache.get("a") is None


def test_sweep_expires_without_any_request(monkeypatch):
    """An idle process must not hold the last documents it saw: the lifespan
    task sweeps on a timer rather than waiting for the next request."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=900.0)
    cache.put("a", entry())
    cache.put("b", entry())

    now = 1901.0
    assert cache.sweep() == 2
    assert cache._entries == {}


def test_discard_forgets_immediately():
    cache = RequestCache()
    cache.put("a", entry())
    cache.discard("a")
    assert cache.get("a") is None
    cache.discard("a")  # already gone: not an error


def test_clear_drops_everything():
    cache = RequestCache()
    cache.put("a", entry())
    cache.put("b", entry())
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_extend_grants_a_full_extension_window(monkeypatch):
    """A press buys the whole extension window from NOW, not another TTL — the
    point is that a reviewer stops racing the countdown."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=900.0, extension_seconds=3600.0, max_lifetime_seconds=43200.0)
    cache.put("a", entry())

    now = 1850.0  # 50 seconds left of the initial 15 minutes
    assert cache.lifetime("a") == (50, True)

    assert cache.extend("a") == (3600, True)
    now = 5000.0  # 52 minutes after creation, still there
    assert cache.get("a") is not None


def test_extension_cannot_cross_the_hard_ceiling(monkeypatch):
    """However often and however long a reviewer extends, the document leaves
    memory at the configured maximum — that ceiling is the retention promise."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    twelve_hours = 12 * 3600.0
    cache = RequestCache(
        ttl_seconds=900.0, extension_seconds=3600.0, max_lifetime_seconds=twelve_hours
    )
    cache.put("a", entry())

    # Extending every ten minutes, right up to the ceiling.
    for _ in range(70):
        now += 600.0
        cache.extend("a")

    now = 1000.0 + twelve_hours - 1  # the last second of its life
    assert cache.get("a") is not None
    assert cache.lifetime("a") == (1, False)  # pinned to the ceiling
    now = 1000.0 + twelve_hours + 1
    assert cache.get("a") is None


def test_extension_reports_when_it_can_no_longer_help(monkeypatch):
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=900.0, extension_seconds=3600.0, max_lifetime_seconds=1200.0)
    cache.put("a", entry())  # expires at 1900, ceiling at 2200

    now = 1500.0
    seconds, can_extend = cache.extend("a")
    assert seconds == 700  # clamped to the ceiling, not now + 3600
    assert can_extend is False  # further clicks would add nothing


def test_extension_keeps_reporting_headroom_right_after_a_click(monkeypatch):
    """`can_extend` is about the ceiling, not about this instant — otherwise
    the button would go dead the moment it is used and revive a minute later."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=900.0, extension_seconds=3600.0, max_lifetime_seconds=43200.0)
    cache.put("a", entry())

    now = 1850.0
    assert cache.extend("a") == (3600, True)
    assert cache.lifetime("a") == (3600, True)


def test_extending_an_expired_entry_reports_it_is_gone(monkeypatch):
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=900.0)
    cache.put("a", entry())

    now = 1901.0
    assert cache.extend("a") is None
    assert cache.lifetime("a") is None


def test_bound_evicts_the_oldest_document(monkeypatch):
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=900.0, max_entries=2)
    cache.put("first", entry("oldest"))
    now += 1
    cache.put("second", entry())
    now += 1
    cache.put("third", entry())

    assert cache.get("first") is None
    assert cache.get("second") is not None
    assert cache.get("third") is not None


class _Settings:
    """Just the fields `configure()` reads."""

    def __init__(self, ttl: int, extension: int, maximum: int, entries: int = 100):
        self.RESULT_CACHE_TTL_MINUTES = ttl
        self.RESULT_CACHE_EXTENSION_MINUTES = extension
        self.RESULT_CACHE_MAX_LIFETIME_MINUTES = maximum
        self.RESULT_CACHE_MAX_ENTRIES = entries


def test_configure_adopts_the_operator_settings(monkeypatch):
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache()
    cache.configure(_Settings(ttl=5, extension=30, maximum=120))

    cache.put("a", entry())
    assert cache.lifetime("a") == (300, True)

    now = 1200.0
    assert cache.extend("a") == (1800, True)  # 30 minutes from now

    now = 1000.0 + 120 * 60 + 1  # past the two-hour ceiling
    assert cache.get("a") is None


def test_configure_leaves_existing_deadlines_alone(monkeypatch):
    """Reconfiguring must not retroactively lengthen the retention of a
    document that is already in memory."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=600.0)
    cache.put("a", entry())

    cache.configure(_Settings(ttl=600, extension=600, maximum=600))

    assert cache.lifetime("a") == (600, True)  # still the original window


def test_a_ceiling_below_the_ttl_shortens_the_first_window(monkeypatch):
    """A misconfiguration must fail toward LESS retention, not more."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache(ttl_seconds=900.0, max_lifetime_seconds=120.0)

    cache.put("a", entry())

    assert cache.lifetime("a") == (120, False)
    now = 1121.0
    assert cache.get("a") is None


def test_a_ceiling_equal_to_the_ttl_turns_extending_off(monkeypatch):
    """The documented way for a strict deployment to disable extension: no
    press can add anything, and the UI never offers the button."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache()
    cache.configure(_Settings(ttl=15, extension=60, maximum=15))

    cache.put("a", entry())
    assert cache.lifetime("a") == (900, False)  # never extendable

    now = 1300.0
    assert cache.extend("a") == (600, False)  # the press bought nothing
    now = 1901.0
    assert cache.get("a") is None


def test_configure_applies_a_tightened_entry_bound_immediately(monkeypatch):
    """Restricting retention must act on what is already in memory, not only
    on the next document."""
    now = 1000.0
    monkeypatch.setattr("backend.src.utils.cache.time.monotonic", lambda: now)
    cache = RequestCache()
    for key in ("a", "b", "c"):
        cache.put(key, entry())
        now += 1

    cache.configure(_Settings(ttl=15, extension=60, maximum=720, entries=1))

    assert cache.get("a") is None
    assert cache.get("b") is None
    assert cache.get("c") is not None
