import json
from pathlib import Path

from backend.src.core.config import Settings
from backend.src.evaluation.data import (
    DEFAULT_LABEL_MAP,
    GroundTruthEntity,
    load_dataset,
    map_label,
)
from backend.src.evaluation.metrics import (
    aggregate,
    char_confusion,
    evaluate_document,
    span_metrics,
)
from backend.src.evaluation.run import evaluate_dataset, main
from backend.src.schemas.entities import EntityType

FIXTURES = Path(__file__).parent.parent / "files"


def gt(start: int, end: int, etype: EntityType, label: str = "") -> GroundTruthEntity:
    return GroundTruthEntity(start=start, end=end, label=label or etype.value, entity_type=etype)


# --- char metrics (LLMAIx-parity semantics) ----------------------------------


def test_char_confusion_excludes_whitespace_and_punctuation():
    text = "Max Mustermann!"
    metrics = char_confusion(text, [(0, 14)], [(0, 14)])
    # 14 span chars minus 1 space = 13 scored positives; "!" is never scored.
    assert (metrics.tp, metrics.fp, metrics.tn, metrics.fn) == (13, 0, 0, 0)
    assert metrics.recall == 1.0


def test_char_confusion_counts_leaked_characters_as_fn():
    text = "Max Mustermann bleibt"
    metrics = char_confusion(text, [(0, 14)], [(4, 14)])  # "Max" leaked
    assert metrics.fn == 3
    assert metrics.tp == 10
    # "bleibt" is unannotated and unredacted → TN.
    assert metrics.tn == len("bleibt")


def test_char_confusion_over_redaction_is_fp():
    text = "Befund unauffällig"
    metrics = char_confusion(text, [], [(0, 6)])
    assert metrics.fp == 6
    assert metrics.fn == 0


# --- span metrics ------------------------------------------------------------


def test_span_exact_vs_overlap():
    gt_spans = [(0, 14)]
    pred_partial = [(0, 3)]
    exact = span_metrics(gt_spans, pred_partial, exact=True)
    overlap = span_metrics(gt_spans, pred_partial, exact=False)
    assert exact.gt_matched == 0
    assert overlap.gt_matched == 1
    assert overlap.recall == 1.0


def test_evaluate_document_missed_entities_have_no_text():
    text = "Max Mustermann und Erika Musterfrau"
    entities = [gt(0, 14, EntityType.PERSON_NAME), gt(19, 35, EntityType.PERSON_NAME)]
    result = evaluate_document("doc", text, entities, [(0, 14)])
    assert result.leaked
    assert len(result.missed_entities) == 1
    assert "text" not in result.missed_entities[0]
    assert result.missed_entities[0]["entity_type"] == "PERSON_NAME"


def test_aggregate_leakage_rate():
    text = "Max Mustermann"
    clean = evaluate_document("a", text, [gt(0, 14, EntityType.PERSON_NAME)], [(0, 14)])
    leaked = evaluate_document("b", text, [gt(0, 14, EntityType.PERSON_NAME)], [])
    agg = aggregate([clean, leaked])
    assert agg["leakage"]["documents_with_leaked_chars"] == 1
    assert agg["leakage"]["leakage_rate"] == 0.5


# --- ground-truth loading ----------------------------------------------------


def test_label_mapping_llmaix_labels():
    warnings: list[str] = []
    assert map_label("patientname", DEFAULT_LABEL_MAP, warnings) == EntityType.PERSON_NAME
    assert map_label("patientid", DEFAULT_LABEL_MAP, warnings) == EntityType.ID_NUMBER
    assert map_label("dateofbirth", DEFAULT_LABEL_MAP, warnings) == EntityType.DATE_OF_BIRTH
    assert warnings == []
    assert map_label("somethingelse", DEFAULT_LABEL_MAP, warnings) == EntityType.OTHER_PII
    assert len(warnings) == 1


def test_load_jsonl_fixture_validates_spans():
    documents = load_dataset(FIXTURES / "eval_example.jsonl")
    assert len(documents) == 2
    first = documents[0]
    assert first.document_id == "synthetic-de-001"
    for entity in first.entities:
        assert 0 <= entity.start < entity.end <= len(first.text)


def test_load_inception_cas_json(tmp_path):
    cas = {
        "%TYPES": [],
        "%FEATURE_STRUCTURES": [
            {
                "%ID": 2,
                "%TYPE": "uima.cas.Sofa",
                "sofaNum": 1,
                "sofaString": "Patient Andrew Smith, born 03/31/1989.",
            },
            {"%ID": 3, "%TYPE": "custom.Span", "begin": 8, "end": 20, "label": "patientname"},
            {"%ID": 4, "%TYPE": "custom.Span", "begin": 27, "end": 37, "label": "dateofbirth"},
            {"%ID": 5, "%TYPE": "custom.Span", "begin": 0, "end": 0, "label": "broken"},
        ],
    }
    path = tmp_path / "0012345.json"
    path.write_text(json.dumps(cas), encoding="utf-8")
    documents = load_dataset(path)
    assert len(documents) == 1
    document = documents[0]
    assert document.document_id == "0012345"
    assert document.text.startswith("Patient Andrew")
    assert [e.entity_type for e in document.entities] == [
        EntityType.PERSON_NAME,
        EntityType.DATE_OF_BIRTH,
    ]
    assert document.text[document.entities[0].start : document.entities[0].end] == "Andrew Smith"
    assert any("invalid CAS span" in w for w in document.warnings)


# --- end-to-end with deterministic detectors ---------------------------------


async def test_evaluate_dataset_with_mock_and_rules():
    documents = load_dataset(FIXTURES / "eval_example.jsonl")
    settings = Settings(DETECTORS="mock,rules")
    report = await evaluate_dataset(documents, settings, mode="detection")
    agg = report["aggregate"]
    # Every annotated entity in the fixture is findable by mock+rules.
    assert agg["leakage"]["documents_with_leaked_chars"] == 0
    assert agg["micro"]["chars"]["recall"] == 1.0
    assert agg["micro"]["spans_overlap"]["recall"] == 1.0
    assert report["config"]["mode"] == "detection"


async def test_redaction_mode_counts_preserved_dates_as_leaks():
    # synthetic-de-002 annotates the treatment date 10.03.2024 as PII; the
    # default policy preserves OTHER_DATE, so redaction mode must flag a leak.
    documents = [d for d in load_dataset(FIXTURES / "eval_example.jsonl") if "002" in d.document_id]
    settings = Settings(DETECTORS="mock,rules")
    detection = await evaluate_dataset(documents, settings, mode="detection")
    redaction = await evaluate_dataset(documents, settings, mode="redaction")
    assert detection["aggregate"]["leakage"]["documents_with_leaked_chars"] == 0
    assert redaction["aggregate"]["leakage"]["documents_with_leaked_chars"] == 1
    missed = redaction["documents"][0]["missed_entities"]
    assert any(m["entity_type"] == "OTHER_DATE" for m in missed)


def test_cli_main_writes_report(tmp_path):
    output = tmp_path / "report.json"
    exit_code = main(
        [
            "--input",
            str(FIXTURES / "eval_example.jsonl"),
            "--output",
            str(output),
            "--detectors",
            "mock,rules",
        ]
    )
    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["aggregate"]["documents"] == 2
    assert report["config"]["detectors"] == ["mock", "rules"]
    # Sensitive text must be excluded by default.
    dumped = json.dumps(report)
    assert "Max Mustermann" not in dumped
