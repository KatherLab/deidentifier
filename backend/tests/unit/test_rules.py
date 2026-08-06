import pytest

from backend.src.schemas.entities import EntityType
from backend.src.utils.rules import RuleBasedDetector

detector = RuleBasedDetector()


async def detect_types(text: str) -> dict[str, EntityType]:
    return {span.text: span.entity_type for span in (await detector.detect(text)).spans}


@pytest.mark.parametrize(
    ("text", "expected_text", "expected_type"),
    [
        (
            "Kontakt: chirurgie@beispiel-klinikum.de bitte",
            "chirurgie@beispiel-klinikum.de",
            EntityType.EMAIL,
        ),
        (
            "Siehe https://portal.beispiel.de/befund?id=1",
            "https://portal.beispiel.de/befund?id=1",
            EntityType.URL,
        ),
        (
            "IBAN: DE89 3704 0044 0532 0130 00 Konto",
            "DE89 3704 0044 0532 0130 00",
            EntityType.ID_NUMBER,
        ),
        ("Tel.: 0351 458-0 erreichbar", "0351 458-0", EntityType.PHONE),
        ("Rufnummer +49 351 4584711 anrufen", "+49 351 4584711", EntityType.PHONE),
        ("Termin am 15.03.2024 vereinbart", "15.03.2024", EntityType.OTHER_DATE),
        ("Befund vom 2024-03-15 liegt vor", "2024-03-15", EntityType.OTHER_DATE),
        ("Am 3. März 2024 aufgenommen", "3. März 2024", EntityType.OTHER_DATE),
        ("Pat.-Nr.: 4711-X eingelesen", "4711-X", EntityType.ID_NUMBER),
        ("Fallnummer: 2024-004711 registriert", "2024-004711", EntityType.ID_NUMBER),
        ("Probe PAT-123456 im Labor", "PAT-123456", EntityType.ID_NUMBER),
        ("wohnhaft Musterstraße 12 in Dresden", "Musterstraße 12", EntityType.ADDRESS),
        ("Adresse: Berliner Straße 12a, Dresden", "Berliner Straße 12a", EntityType.ADDRESS),
        ("in der Hauptstr. 5 wohnhaft", "Hauptstr. 5", EntityType.ADDRESS),
        ("PLZ 01307 Dresden angegeben", "01307 Dresden", EntityType.ADDRESS),
        (
            "Klinik für Kardiologie, Musterstadt",
            "Klinik für Kardiologie",
            EntityType.ORGANIZATION,
        ),
        (
            "Klinik und Poliklinik für Innere Medizin\nMusterstraße 74",
            "Klinik und Poliklinik für Innere Medizin",
            EntityType.ORGANIZATION,
        ),
        (
            "Klinik für Viszeral-, Thorax- und Gefäßchirurgie",
            "Klinik für Viszeral-, Thorax- und Gefäßchirurgie",
            EntityType.ORGANIZATION,
        ),
        ("Medizinische Klinik I, Chefarzt", "Medizinische Klinik I", EntityType.ORGANIZATION),
        ("Sektion Rheumatologie am Haus", "Sektion Rheumatologie", EntityType.ORGANIZATION),
        ("Verlegung auf Station 4B erfolgt", "Station 4B", EntityType.ORGANIZATION),
        ("Ambulanz in Haus 12 gelegen", "Haus 12", EntityType.ORGANIZATION),
    ],
)
async def test_recognizers(text: str, expected_text: str, expected_type: EntityType):
    found = await detect_types(text)
    assert found.get(expected_text) == expected_type, f"got {found}"


@pytest.mark.parametrize(
    "text",
    [
        # Bare nouns in running text are not organizational units.
        "Der Patient wurde im Krankenhaus behandelt und auf die Station gebracht.",
        "Wiedervorstellung in der Ambulanz Anfang Mai",
        "Die Klinik hat den Befund übermittelt.",
    ],
)
async def test_no_generic_units_detected(text: str):
    spans = (await detector.detect(text)).spans
    assert [s for s in spans if s.entity_type == EntityType.ORGANIZATION] == []


async def test_unit_name_stops_at_the_next_field():
    """A unit name may not run on past its own line or field — a comma
    continues it only inside a compound enumeration ("Viszeral-, Thorax-")."""
    found = await detect_types(
        "Zentrum für Innere Medizin und Dermatologie, Station K1\nProf. Dr. Anna Beispiel"
    )
    assert found.get("Zentrum für Innere Medizin und Dermatologie") == EntityType.ORGANIZATION
    assert found.get("Station K1") == EntityType.ORGANIZATION


async def test_department_carries_subtype():
    spans = (await detector.detect("Abteilung für Neurologie, Station 3")).spans
    subtypes = {s.text: s.metadata.get("subtype") for s in spans}
    assert subtypes["Abteilung für Neurologie"] == "department"
    assert subtypes["Station 3"] == "ward"


async def test_dob_label_beats_generic_date():
    spans = (await detector.detect("geb. 01.02.1980 in Dresden")).spans
    dob = [s for s in spans if s.entity_type == EntityType.DATE_OF_BIRTH]
    assert len(dob) == 1
    assert dob[0].text == "01.02.1980"
    assert dob[0].confidence > 0.9


async def test_offsets_match_source_with_umlauts():
    text = "Übergabe: Müllerstraße 3, Tel.: 0351 4584711, geb. 01.02.1980, ärztlich betreut"
    for span in (await detector.detect(text)).spans:
        assert text[span.start : span.end] == span.text


async def test_no_bare_numbers_detected():
    outcome = await detector.detect("Der Patient erhielt 500 mg Metamizol, Laborwert 123456.")
    assert outcome.spans == []


async def test_every_span_carries_rule_id():
    spans = (await detector.detect("Tel.: 0351 458-0, Fallnummer: 471123")).spans
    assert spans
    for span in spans:
        assert span.metadata.get("rule_id", "").startswith("de.")
