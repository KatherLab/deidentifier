from backend.src.schemas.entities import EntitySpan, EntityType
from backend.src.utils.resolver import resolve_spans


def span(
    start: int, end: int, text: str, etype: EntityType, conf: float, detector: str
) -> EntitySpan:
    return EntitySpan(
        start=start, end=end, text=text, entity_type=etype, confidence=conf, detector=detector
    )


def test_exact_duplicates_merge_with_provenance():
    spans = [
        span(0, 14, "Max Mustermann", EntityType.PERSON_NAME, 0.9, "rules"),
        span(0, 14, "Max Mustermann", EntityType.PERSON_NAME, 1.0, "mock"),
    ]
    resolved, decisions = resolve_spans(spans)
    assert len(resolved) == 1
    assert resolved[0].confidence == 1.0
    assert "mock" in resolved[0].metadata["supporting_detectors"]
    assert "rules" in resolved[0].metadata["supporting_detectors"]
    assert decisions and decisions[0].reason == "duplicate span merged"


def test_identical_offsets_higher_confidence_type_wins():
    spans = [
        span(5, 15, "01.02.1980", EntityType.OTHER_DATE, 0.9, "rules"),
        span(5, 15, "01.02.1980", EntityType.DATE_OF_BIRTH, 0.97, "rules"),
    ]
    resolved, decisions = resolve_spans(spans)
    assert len(resolved) == 1
    assert resolved[0].entity_type == EntityType.DATE_OF_BIRTH
    assert len(decisions) == 1


def test_contained_span_dropped_with_decision():
    spans = [
        span(0, 15, "Musterstraße 12", EntityType.ADDRESS, 0.9, "rules"),
        span(0, 12, "Musterstraße", EntityType.ADDRESS, 0.95, "rules"),
    ]
    resolved, decisions = resolve_spans(spans)
    assert len(resolved) == 1
    assert resolved[0].end == 15
    assert decisions[0].rejected[0].end == 12


def test_non_overlapping_spans_all_kept():
    spans = [
        span(0, 4, "abcd", EntityType.ID_NUMBER, 0.8, "rules"),
        span(10, 14, "efgh", EntityType.ID_NUMBER, 0.8, "rules"),
        span(4, 8, "wxyz", EntityType.PHONE, 0.8, "rules"),
    ]
    resolved, decisions = resolve_spans(spans)
    assert len(resolved) == 3
    assert decisions == []
    assert [s.start for s in resolved] == [0, 4, 10]


def test_empty_input():
    assert resolve_spans([]) == ([], [])
