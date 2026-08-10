"""Named vision-OCR profiles: parsing, inheritance, and loud refusal of
anything unknown or malformed."""

import json

import pytest

from backend.src.core.config import Settings, validate_production_settings
from backend.src.utils.ocr_profiles import (
    OcrProfileError,
    parse_profiles,
    resolve_vision_ocr_profile,
)

_TWO_PROFILES = json.dumps(
    [
        {"name": "Chandra", "model": "chandra-ocr-2", "dialect": "chandra"},
        {"name": "Unlimited", "model": "baidu/Unlimited-OCR", "dialect": "unlimited_ocr"},
    ]
)


def settings_with(**overrides) -> Settings:
    defaults = dict(
        OCR_ENGINE="llm_vision",
        VISION_OCR_API_BASE="http://ocr:8100/v1",
        VISION_OCR_API_KEY="base-key",
        VISION_OCR_MODEL="flat-model",
    )
    defaults.update(overrides)
    return Settings(**defaults)


# --- parsing -----------------------------------------------------------------


def test_unset_profiles_means_feature_off():
    assert parse_profiles(settings_with()) == []


def test_two_profiles_parse():
    profiles = parse_profiles(settings_with(VISION_OCR_PROFILES=_TWO_PROFILES))
    assert [p.name for p in profiles] == ["Chandra", "Unlimited"]


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"name": "x"}',  # object, not list
        '[{"model": "m"}]',  # missing name
        '[{"name": "x"}]',  # missing model
        '[{"name": "x", "model": "m", "modle_typo": true}]',  # unknown key
        '[{"name": "x", "model": "m"}, {"name": "x", "model": "m2"}]',  # duplicate
        '[{"name": "x", "model": "m", "dialect": "nope"}]',  # unknown dialect
    ],
)
def test_malformed_profiles_are_refused(raw):
    with pytest.raises(OcrProfileError):
        parse_profiles(settings_with(VISION_OCR_PROFILES=raw))


def test_production_refuses_malformed_profiles():
    settings = settings_with(APP_ENV="production", VISION_OCR_PROFILES="not json")
    with pytest.raises(RuntimeError, match="VISION_OCR_PROFILES"):
        validate_production_settings(settings)


# --- resolution --------------------------------------------------------------


def test_no_profiles_and_no_selection_keeps_flat_settings():
    settings = settings_with()
    assert resolve_vision_ocr_profile(settings, None) is settings


def test_selection_without_configured_profiles_is_422():
    with pytest.raises(OcrProfileError) as excinfo:
        resolve_vision_ocr_profile(settings_with(), "Chandra")
    assert excinfo.value.status_code == 422


def test_default_is_the_first_profile():
    resolved = resolve_vision_ocr_profile(settings_with(VISION_OCR_PROFILES=_TWO_PROFILES), None)
    assert resolved.VISION_OCR_MODEL == "chandra-ocr-2"
    assert resolved.VISION_OCR_DIALECT == "chandra"


def test_selected_profile_wins():
    resolved = resolve_vision_ocr_profile(
        settings_with(VISION_OCR_PROFILES=_TWO_PROFILES), "Unlimited"
    )
    assert resolved.VISION_OCR_MODEL == "baidu/Unlimited-OCR"
    assert resolved.VISION_OCR_DIALECT == "unlimited_ocr"
    # Unset profile fields inherit the flat settings.
    assert resolved.VISION_OCR_API_BASE == "http://ocr:8100/v1"
    assert resolved.VISION_OCR_API_KEY == "base-key"


def test_unknown_selection_is_422_and_names_the_configured_profiles():
    with pytest.raises(OcrProfileError) as excinfo:
        resolve_vision_ocr_profile(settings_with(VISION_OCR_PROFILES=_TWO_PROFILES), "nope")
    assert excinfo.value.status_code == 422
    assert "Chandra" in str(excinfo.value)


def test_profile_overrides_endpoint_and_recipe():
    profiles = json.dumps(
        [
            {
                "name": "gpu-box",
                "model": "some-ocr",
                "api_base": "http://gpu:8100/v1",
                "api_key": "other-key",
                "prompt": "custom",
                "max_tokens": 4096,
                "extra_body": {"vllm_xargs": {"ngram_size": 10}},
            }
        ]
    )
    resolved = resolve_vision_ocr_profile(settings_with(VISION_OCR_PROFILES=profiles), "gpu-box")
    assert resolved.VISION_OCR_API_BASE == "http://gpu:8100/v1"
    assert resolved.VISION_OCR_API_KEY == "other-key"
    assert resolved.VISION_OCR_PROMPT == "custom"
    assert resolved.VISION_OCR_MAX_TOKENS == 4096
    assert json.loads(resolved.VISION_OCR_EXTRA_BODY) == {"vllm_xargs": {"ngram_size": 10}}
