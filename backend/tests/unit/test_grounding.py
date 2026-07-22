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


def test_name_parts_grounded_standalone():
    # The LLM reports the full name once; the standalone first name later in
    # the text must still be caught.
    text = "Elisabeth Bauer wurde aufgenommen. Später berichtete Elisabeth über Beschwerden."
    spans, warnings = ground_mentions(
        text, [Mention("Elisabeth Bauer", EntityType.PERSON_NAME, "patient")]
    )
    assert warnings == []
    texts = sorted(text[s.start : s.end] for s in spans)
    assert texts == ["Elisabeth", "Elisabeth Bauer"]
    part = next(s for s in spans if s.metadata.get("grounding") == "name_part")
    assert text[part.start : part.end] == "Elisabeth"


def test_name_parts_skip_titles_and_covered_occurrences():
    text = "Dr. med. Anna Beispiel behandelte. Anna kam später."
    spans, _ = ground_mentions(
        text, [Mention("Dr. med. Anna Beispiel", EntityType.PERSON_NAME, "clinician")]
    )
    texts = sorted(text[s.start : s.end] for s in spans)
    # Full mention once, standalone "Anna" once — no span for "med"/"Dr" and no
    # duplicate for the "Anna" inside the full mention.
    assert texts == ["Anna", "Dr. med. Anna Beispiel"]


def test_non_name_mentions_cover_case_variants():
    # "Gender: Female" is reported by the LLM; the lowercase inline use must
    # also be covered.
    text = "Gender: Female. The patient is a 48-year-old female with hypertension."
    spans, warnings = ground_mentions(text, [Mention("Female", EntityType.OTHER_PII)])
    assert warnings == []
    assert sorted(text[s.start : s.end] for s in spans) == ["Female", "female"]


def test_person_names_stay_case_strict():
    # "Ernst" is a surname AND a common German word — names must not expand
    # to case variants.
    text = "Ernst kam zur Kontrolle. Die Lage ist ernst."
    spans, _ = ground_mentions(text, [Mention("Ernst", EntityType.PERSON_NAME)])
    assert [text[s.start : s.end] for s in spans] == ["Ernst"]


def test_umlaut_variant_grounding():
    # OCR text uses the digraph spelling; the LLM reports the umlaut form.
    text = "Patient Hans Mueller wurde entlassen."
    spans, warnings = ground_mentions(text, [Mention("Hans Müller", EntityType.PERSON_NAME)])
    assert warnings == []
    assert any(text[s.start : s.end] == "Hans Mueller" for s in spans)
    full = next(s for s in spans if s.text == "Hans Mueller")
    assert full.metadata["grounding"] == "partial"


def test_dehyphenated_grounding():
    text = "Der Befund von Max Muster-\nmann liegt vor."
    spans, warnings = ground_mentions(text, [Mention("Max Mustermann", EntityType.PERSON_NAME)])
    assert warnings == []
    assert any(text[s.start : s.end] == "Max Muster-\nmann" for s in spans)


def test_duplicate_mentions_do_not_duplicate_spans():
    text = "PAT-123456 liegt vor."
    mentions = [
        Mention("PAT-123456", EntityType.ID_NUMBER),
        Mention("PAT-123456", EntityType.ID_NUMBER),
    ]
    spans, _ = ground_mentions(text, mentions)
    assert len(spans) == 1
