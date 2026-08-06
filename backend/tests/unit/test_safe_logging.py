import logging

from backend.src.core.config import get_settings
from backend.src.utils.safe_logging import get_safe_logger, log_reference


def test_forbidden_fields_rejected(caplog):
    logger = get_safe_logger("test.safe")
    with caplog.at_level(logging.INFO, logger="test.safe"):
        logger.info("event", text="Max Mustermann", chars=14, entity_text="secret")
    output = caplog.text
    assert "Max Mustermann" not in output
    assert "secret" not in output
    assert "chars=14" in output
    assert "rejected_fields=entity_text,text" in output


def test_request_id_is_never_logged(caplog):
    """The request id is a capability: it fetches the cached document from the
    API for as long as the entry lives, so it must not reach a log."""
    logger = get_safe_logger("test.safe.rid")
    with caplog.at_level(logging.INFO, logger="test.safe.rid"):
        logger.info("event", request_id="9f8e7d6c-1111-2222-3333-444455556666")
    assert "9f8e7d6c" not in caplog.text
    assert "rejected_fields=request_id" in caplog.text


def test_log_reference_is_short_stable_and_not_the_id():
    request_id = "9f8e7d6c-1111-2222-3333-444455556666"
    reference = log_reference(request_id)
    assert reference == log_reference(request_id)
    assert len(reference) == 12
    assert request_id not in reference
    assert reference != log_reference("9f8e7d6c-1111-2222-3333-444455556667")


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
