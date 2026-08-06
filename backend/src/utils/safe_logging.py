"""Structured logger that refuses document content.

Fields with names known to carry document content — or a credential for it —
are dropped (and noted as rejected) unless APP_ALLOW_INSECURE_CONTENT_LOGGING
is enabled. This is the only logger the application code may use.
"""

import hashlib
import logging

FORBIDDEN_FIELDS = {
    "text",
    "document",
    "content",
    "prompt",
    "filename",
    "entity_text",
    "anonymized_text",
    "source_text",
    # Not content, but the only key to it: anyone holding a request id can ask
    # the API for the cached document while the entry lives. Log
    # `ref=log_reference(request_id)` instead.
    "request_id",
}


def log_reference(value: str) -> str:
    """A short, non-reversible handle for correlating log lines about one
    request, safe to write where the request id itself is not."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class SafeLogger:
    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _sanitize(self, fields: dict) -> dict:
        from ..core.config import get_settings

        if get_settings().APP_ALLOW_INSECURE_CONTENT_LOGGING:
            return fields
        rejected = sorted(k for k in fields if k.lower() in FORBIDDEN_FIELDS)
        if rejected:
            fields = {k: v for k, v in fields.items() if k.lower() not in FORBIDDEN_FIELDS}
            fields["rejected_fields"] = ",".join(rejected)
        return fields

    def _log(self, level: int, event: str, fields: dict) -> None:
        payload = self._sanitize(fields)
        extras = " ".join(f"{key}={value}" for key, value in payload.items())
        self._logger.log(level, "%s %s", event, extras)

    def info(self, event: str, **fields: object) -> None:
        self._log(logging.INFO, event, fields)

    def warning(self, event: str, **fields: object) -> None:
        self._log(logging.WARNING, event, fields)

    def error(self, event: str, **fields: object) -> None:
        self._log(logging.ERROR, event, fields)


def get_safe_logger(name: str) -> SafeLogger:
    return SafeLogger(logging.getLogger(name))
