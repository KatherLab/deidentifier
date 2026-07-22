from backend.src.schemas.entities import EntitySpan, EntityType, SpanStatus
from backend.src.utils.transformation import apply_policy


def span(start: int, end: int, text: str, etype: EntityType) -> EntitySpan:
    return EntitySpan(
        start=start, end=end, text=text, entity_type=etype, confidence=0.9, detector="test"
    )


def make(text: str, fragments: list[tuple[str, EntityType]]) -> tuple[str, list[EntitySpan]]:
    spans = []
    for fragment, etype in fragments:
        start = text.index(fragment)
        spans.append(span(start, start + len(fragment), fragment, etype))
    return text, spans


def test_consistent_tags_repeat_and_increment():
    text, spans = make(
        "Max Mustermann traf Erika Musterfrau. Später kam Max Mustermann zurück.",
        [
            ("Max Mustermann", EntityType.PERSON_NAME),
            ("Erika Musterfrau", EntityType.PERSON_NAME),
        ],
    )
    second = text.rindex("Max Mustermann")
    spans.append(span(second, second + 14, "Max Mustermann", EntityType.PERSON_NAME))
    result, applied, _ = apply_policy(text, spans)
    assert result == "[PERSON_1] traf [PERSON_2]. Später kam [PERSON_1] zurück."
    assert all(e.status == SpanStatus.TAGGED for e in applied)


def test_right_to_left_application_keeps_offsets_valid():
    text, spans = make(
        "Tel.: 0351 458-0, Musterstraße 12, chirurgie@beispiel.de",
        [
            ("0351 458-0", EntityType.PHONE),
            ("Musterstraße 12", EntityType.ADDRESS),
            ("chirurgie@beispiel.de", EntityType.EMAIL),
        ],
    )
    result, _, _ = apply_policy(text, spans)
    assert result == "Tel.: [TELEFON], [ADRESSE], [E-MAIL]"


def test_dob_generalized_to_year():
    text, spans = make(
        "geboren am 01.02.1980 in Dresden", [("01.02.1980", EntityType.DATE_OF_BIRTH)]
    )
    result, applied, _ = apply_policy(text, spans)
    assert result == "geboren am 1980 in Dresden"
    assert applied[0].status == SpanStatus.GENERALIZED
    assert applied[0].replacement == "1980"


def test_dates_preserved_by_default():
    text, spans = make("Aufnahme am 10.03.2024 erfolgt", [("10.03.2024", EntityType.OTHER_DATE)])
    result, applied, _ = apply_policy(text, spans)
    assert result == text
    assert applied[0].status == SpanStatus.PRESERVED
    assert applied[0].replacement is None


def test_source_text_not_mutated_and_unicode_offsets_survive():
    text, spans = make(
        "Ärztin übergab Max Mustermann größere Befunde",
        [("Max Mustermann", EntityType.PERSON_NAME)],
    )
    original = text
    result, applied, _ = apply_policy(text, spans)
    assert text == original
    assert result == "Ärztin übergab [PERSON_1] größere Befunde"
    # Applied entities keep source offsets, not output offsets.
    assert original[applied[0].start : applied[0].end] == "Max Mustermann"


def test_text_outside_spans_untouched():
    text, spans = make("Vorher PAT-123456 nachher", [("PAT-123456", EntityType.ID_NUMBER)])
    result, _, _ = apply_policy(text, spans)
    assert result.startswith("Vorher ") and result.endswith(" nachher")
    assert "[ID]" in result


def test_override_preserve_beats_policy():
    from backend.src.schemas.anonymize import EntityOverride
    from backend.src.schemas.entities import TransformationType

    text, spans = make(
        "Klinikum Beispielstadt behandelte", [("Klinikum Beispielstadt", EntityType.ORGANIZATION)]
    )
    override = EntityOverride(
        start=spans[0].start,
        end=spans[0].end,
        text=spans[0].text,
        transformation=TransformationType.PRESERVE,
    )
    result, applied, warnings = apply_policy(text, spans, overrides=[override])
    assert result == text
    assert applied[0].status == SpanStatus.PRESERVED
    assert applied[0].metadata.get("overridden") is True
    assert warnings == []


def test_override_can_change_entity_type():
    from backend.src.schemas.anonymize import EntityOverride

    text, spans = make(
        "Kontakt Beispielfirma GmbH hier", [("Beispielfirma GmbH", EntityType.OTHER_PII)]
    )
    override = EntityOverride(
        start=spans[0].start,
        end=spans[0].end,
        text=spans[0].text,
        entity_type=EntityType.ORGANIZATION,
    )
    result, applied, _ = apply_policy(text, spans, overrides=[override])
    assert "[ORGANISATION]" in result
    assert applied[0].entity_type == EntityType.ORGANIZATION


def test_unmatched_override_produces_warning():
    from backend.src.schemas.anonymize import EntityOverride
    from backend.src.schemas.entities import TransformationType

    text, spans = make("Vorher PAT-123456 nachher", [("PAT-123456", EntityType.ID_NUMBER)])
    override = EntityOverride(
        start=0, end=6, text="Vorher", transformation=TransformationType.PRESERVE
    )
    result, _, warnings = apply_policy(text, spans, overrides=[override])
    assert "[ID]" in result
    assert len(warnings) == 1
