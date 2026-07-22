from backend.src.schemas.entities import EntityType
from backend.src.utils.grounding import Mention, ground_mentions


def test_exact_match_grounds_all_occurrences():
    text = "Max Mustermann kam. Später ging Max Mustermann."
    spans, warnings = ground_mentions(
        text, [Mention("Max Mustermann", EntityType.PERSON_NAME, "patient")]
    )
    assert warnings == []
    assert len(spans) == 2
    for span in spans:
        assert text[span.start : span.end] == "Max Mustermann"
        assert span.metadata["role"] == "patient"
        assert span.detector == "llm"


def test_whitespace_normalized_fallback():
    # The LLM collapsed a line break inside the mention.
    text = "Patient: Max\nMustermann wurde entlassen."
    spans, warnings = ground_mentions(text, [Mention("Max Mustermann", EntityType.PERSON_NAME)])
    assert warnings == []
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == "Max\nMustermann"


def test_case_insensitive_last_resort():
    text = "der patient max mustermann"
    spans, warnings = ground_mentions(text, [Mention("Max Mustermann", EntityType.PERSON_NAME)])
    assert warnings == []
    assert len(spans) == 1


def test_unlocatable_mention_becomes_warning_without_content():
    spans, warnings = ground_mentions(
        "Ganz anderer Text.", [Mention("Erika Musterfrau", EntityType.PERSON_NAME)]
    )
    assert spans == []
    assert len(warnings) == 1
    assert "Erika" not in warnings[0]
    assert "PERSON_NAME" in warnings[0]


def test_trivially_short_mentions_are_skipped():
    spans, warnings = ground_mentions("M und mehr Text", [Mention("M", EntityType.OTHER_PII)])
    assert spans == []
    assert warnings == []


def test_inflected_salutation_grounds_via_leading_token_trim():
    # LLM normalized German dative "Herrn" to "Herr" — the exact string is not
    # in the text, but dropping the leading token must still find the name.
    text = "wurde von ihrem Ehemann Herrn Wolfgang Schäfer vorgestellt"
    spans, warnings = ground_mentions(
        text, [Mention("Herr Wolfgang Schäfer", EntityType.PERSON_NAME, "relative")]
    )
    assert warnings == []
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == "Wolfgang Schäfer"
    assert spans[0].metadata["grounding"] == "partial"


def test_trimmed_needle_requires_word_boundaries():
    # "Meier" appears only inside "Meierhof" — trimming must not match there.
    text = "Der Meierhof liegt am Ortsrand."
    spans, warnings = ground_mentions(text, [Mention("Klaus Meier", EntityType.PERSON_NAME)])
    assert spans == []
    assert len(warnings) == 1


def test_duplicate_mentions_do_not_duplicate_spans():
    text = "PAT-123456 liegt vor."
    mentions = [
        Mention("PAT-123456", EntityType.ID_NUMBER),
        Mention("PAT-123456", EntityType.ID_NUMBER),
    ]
    spans, _ = ground_mentions(text, mentions)
    assert len(spans) == 1
