import json

import pytest

from backend.src.core.config import Settings
from backend.src.schemas.entities import EntityType
from backend.src.utils.detection import DetectorError
from backend.src.utils.llm_detection import LLMDetector, chunk_text, parse_llm_response


def settings_with(**kwargs) -> Settings:
    defaults = {
        "OPENAI_API_BASE": "http://localhost:11434/v1",
        "LLM_MODEL": "test-model",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


# --- chunking ----------------------------------------------------------------


def test_single_chunk_for_short_text():
    assert chunk_text("kurz", 100, 10) == ["kurz"]


def test_chunks_overlap_and_cover_everything():
    text = "abcdefghij" * 100  # 1000 chars
    chunks = chunk_text(text, 300, 50)
    assert all(len(c) <= 300 for c in chunks)
    # Reconstruction: consecutive chunks overlap by 50 chars.
    step = 250
    for i, chunk in enumerate(chunks):
        assert text[i * step : i * step + len(chunk)] == chunk
    assert (len(chunks) - 1) * step + len(chunks[-1]) >= len(text)


# --- response parsing --------------------------------------------------------


def test_parse_object_response():
    content = json.dumps(
        {"entities": [{"text": "Max Mustermann", "type": "PERSON_NAME", "role": "patient"}]}
    )
    mentions = parse_llm_response(content)
    assert len(mentions) == 1
    assert mentions[0].entity_type == EntityType.PERSON_NAME
    assert mentions[0].role == "patient"


def test_parse_bare_array_and_markdown_fence():
    content = '```json\n[{"text": "01307 Dresden", "type": "ADDRESS"}]\n```'
    mentions = parse_llm_response(content)
    assert len(mentions) == 1
    assert mentions[0].entity_type == EntityType.ADDRESS


def test_unknown_type_maps_to_other_pii():
    content = json.dumps({"entities": [{"text": "irgendwas", "type": "MADE_UP_TYPE"}]})
    mentions = parse_llm_response(content)
    assert mentions[0].entity_type == EntityType.OTHER_PII


def test_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_llm_response("Das ist kein JSON.")


# --- detector ----------------------------------------------------------------


async def test_detector_grounds_llm_output(monkeypatch):
    detector = LLMDetector(settings_with())

    async def fake_chat(kwargs):
        return json.dumps(
            {
                "entities": [
                    {"text": "Max Mustermann", "type": "PERSON_NAME", "role": "patient"},
                    {"text": "nicht im Dokument", "type": "ORGANIZATION", "role": ""},
                ]
            }
        )

    monkeypatch.setattr(detector, "_chat", fake_chat)
    text = "Patient: Max Mustermann wurde behandelt. Max Mustermann geht es gut."
    outcome = await detector.detect(text)
    assert len(outcome.spans) == 2  # both occurrences grounded
    assert all(text[s.start : s.end] == "Max Mustermann" for s in outcome.spans)
    assert len(outcome.warnings) == 1  # the unlocatable ORGANIZATION mention
    assert "ORGANIZATION" in outcome.warnings[0]


async def test_detector_fails_closed_on_persistent_invalid_json(monkeypatch):
    detector = LLMDetector(settings_with())

    async def fake_chat(kwargs):
        return "kein json"

    monkeypatch.setattr(detector, "_chat", fake_chat)
    with pytest.raises(DetectorError):
        await detector.detect("Ein kurzer Text.")


async def test_detector_unreachable_endpoint_raises_detector_error():
    # Port 9 (discard) refuses connections immediately.
    detector = LLMDetector(
        settings_with(OPENAI_API_BASE="http://127.0.0.1:9/v1", LLM_REQUEST_TIMEOUT_SECONDS=2)
    )
    with pytest.raises(DetectorError):
        await detector.detect("Ein kurzer Text.")
