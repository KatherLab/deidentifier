import os

import pytest

# Must be set before any backend module is imported so the cached Settings
# instance picks it up. ENV_PATH points at a nonexistent file so a developer's
# backend/.env (which may contain real endpoints) never leaks into tests.
os.environ["ENV_PATH"] = "backend/.env.does-not-exist"
os.environ.setdefault("DETECTORS", "mock,rules")

from backend.src.core.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _pristine_request_cache():
    """The detection cache is a process-wide singleton holding document text.

    No test may leave entries — or a test-specific lifetime configuration —
    behind for the next one. Runs after `monkeypatch` has restored the
    environment, so the reconstructed `Settings` are the shipped defaults.
    """
    yield
    from backend.src.core.config import Settings
    from backend.src.utils.cache import request_cache

    request_cache.clear()
    request_cache.configure(Settings())


@pytest.fixture()
def client():
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from backend.src.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
