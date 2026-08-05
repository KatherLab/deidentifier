"""The notice catalog is the backend half of the translation contract: every
code the pipeline can emit must have English text here, and the frontend
catalogs must know the same codes."""

import json
from pathlib import Path

import pytest

from backend.src.schemas.entities import ValidationSeverity
from backend.src.utils import notices
from backend.src.utils.notices import notice, validation_warning

_LOCALES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "locales"

# Codes with placeholders, and a sample value for each.
_PARAMS = {
    notices.PDF_DOCLING_FALLBACK: {"reason": "timeout"},
    notices.LLM_MENTION_NOT_LOCATED: {"entity_type": "PERSON_NAME"},
    notices.INVALID_SPAN_REJECTED: {"detector": "llm"},
    notices.RESIDUAL_IDENTIFIER: {"entity_type": "EMAIL"},
    notices.REVALIDATION_HIT: {"entity_type": "PHONE"},
    notices.LLM_RECHECK_REMAINING: {"entity_type": "ADDRESS"},
    notices.RECHECK_RISK: {"risk": "high"},
}


def _all_codes() -> list[str]:
    return sorted(notices._MESSAGES)


@pytest.mark.parametrize("code", _all_codes())
def test_every_code_renders_english_text(code):
    built = notice(code, **_PARAMS.get(code, {}))
    assert built.code == code
    assert built.message.strip()
    # No unfilled placeholder survived into the fallback text.
    assert "{" not in built.message


@pytest.mark.parametrize("code", _all_codes())
def test_every_code_has_a_message_in_every_locale(code):
    for path in sorted(_LOCALES_DIR.glob("*.json")):
        catalog = json.loads(path.read_text(encoding="utf-8"))
        assert code in catalog["warnings"]["codes"], f"{code} missing from {path.name}"


def test_validation_warning_carries_code_and_params():
    warning = validation_warning(
        notices.RESIDUAL_IDENTIFIER,
        category="residual_identifier",
        severity=ValidationSeverity.HIGH,
        start=3,
        end=9,
        entity_type="EMAIL",
    )
    assert warning.code == notices.RESIDUAL_IDENTIFIER
    assert warning.params == {"entity_type": "EMAIL"}
    assert warning.severity == ValidationSeverity.HIGH
    assert (warning.start, warning.end) == (3, 9)
    assert "EMAIL" in warning.message
