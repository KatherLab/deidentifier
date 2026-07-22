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


def test_chunks_cover_everything_and_prefer_boundaries():
    # Unique paragraph markers so positions are unambiguous.
    text = "\n\n".join(f"Absatz {i}: " + "Befundtext ohne Namen. " * 8 for i in range(40))
    chunks = chunk_text(text, 1000, 200)
    assert len(chunks) > 3
    assert all(len(chunk) <= 1000 for chunk in chunks)
    # Full coverage with overlap: each chunk starts at or before the previous end.
    position = 0
    for chunk in chunks:
        index = text.find(chunk, max(0, position - 400))
        assert index != -1 and index <= position
        position = index + len(chunk)
    assert position == len(text)
    # Boundary preference: intermediate chunks end at paragraph/line/sentence breaks.
    for chunk in chunks[:-1]:
        assert chunk.endswith(("\n\n", "\n", ". "))


def test_chunks_fall_back_to_hard_cut_without_separators():
    text = "x" * 3000  # no separators at all
    chunks = chunk_text(text, 1000, 100)
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert sum(len(c) for c in chunks) >= 3000  # everything covered (with overlap)


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


async def test_multi_pass_unions_results(monkeypatch):
    detector = LLMDetector(settings_with(LLM_DETECTION_PASSES=2))
    calls = []

    async def fake_chat(kwargs):
        calls.append(kwargs["temperature"])
        if len(calls) == 1:
            return json.dumps(
                {"entities": [{"text": "Johann Schmidt", "type": "PERSON_NAME", "role": ""}]}
            )
        return json.dumps({"entities": [{"text": "0351 4584711", "type": "PHONE", "role": ""}]})

    monkeypatch.setattr(detector, "_chat", fake_chat)
    text = "Johann Schmidt, erreichbar unter 0351 4584711."
    outcome = await detector.detect(text)
    assert len(calls) == 2
    assert calls[0] != calls[1]  # first pass temperature 0, second samples
    found = {s.text for s in outcome.spans}
    assert found == {"Johann Schmidt", "0351 4584711"}


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


async def test_truncated_output_bisects_chunk(monkeypatch):
    from backend.src.utils.llm_detection import _TruncatedOutputError

    detector = LLMDetector(settings_with(LLM_DETECTION_PASSES=1))

    async def fake_chat(kwargs):
        user = kwargs["messages"][1]["content"]
        # The full chunk (both names present) exceeds the output budget;
        # the bisected halves succeed.
        if "Anna Alt" in user and "Bernd Neu" in user:
            raise _TruncatedOutputError()
        if "Anna Alt" in user:
            return json.dumps(
                {"entities": [{"text": "Anna Alt", "type": "PERSON_NAME", "role": ""}]}
            )
        return json.dumps({"entities": [{"text": "Bernd Neu", "type": "PERSON_NAME", "role": ""}]})

    monkeypatch.setattr(detector, "_chat", fake_chat)
    text = "Anna Alt wurde untersucht. " + "Befund unauffällig. " * 50 + "Bernd Neu übernahm."
    outcome = await detector.detect(text)
    assert {s.text for s in outcome.spans} == {"Anna Alt", "Bernd Neu"}


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
