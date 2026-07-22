import logging

from backend.src.core.config import get_settings
from backend.src.utils.safe_logging import get_safe_logger


def test_forbidden_fields_rejected(caplog):
    logger = get_safe_logger("test.safe")
    with caplog.at_level(logging.INFO, logger="test.safe"):
        logger.info("event", text="Max Mustermann", request_id="abc", entity_text="secret")
    output = caplog.text
    assert "Max Mustermann" not in output
    assert "secret" not in output
    assert "request_id=abc" in output
    assert "rejected_fields=entity_text,text" in output


def test_forbidden_fields_allowed_with_insecure_flag(caplog, monkeypatch):
    monkeypatch.setenv("APP_ALLOW_INSECURE_CONTENT_LOGGING", "true")
    get_settings.cache_clear()
    try:
        logger = get_safe_logger("test.safe.insecure")
        with caplog.at_level(logging.INFO, logger="test.safe.insecure"):
            logger.info("event", text="Max Mustermann")
        assert "Max Mustermann" in caplog.text
    finally:
        get_settings.cache_clear()
