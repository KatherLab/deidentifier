"""Evaluation harness CLI — runs the real detection pipeline over annotated
documents and reports character-, span- and document-level metrics.

Usage (from the repo root):

    uv run python -m backend.src.evaluation.run \
        --input annotated.jsonl \
        --output evaluation-results.json \
        --detectors rules,llm \
        --mode detection

Inputs: our JSONL format, INCEpTION UIMA-CAS JSON files (LLMAIx annotation
export), a directory of either, or a .zip of CAS files. Modes:
  detection  — every detected span counts (measures the detectors)
  redaction  — only spans the default policy actually masks count; entities
               the policy preserves (e.g. clinical dates) count as leaks if
               they are annotated as PII.

This tool is deliberately separate from the web UI. By default the report
contains no literal entity text — pass --include-sensitive-text for a
debugging report that does (clearly labelled, handle accordingly).
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from ..core.config import Settings, get_settings
from ..schemas.entities import TransformationType
from ..utils.detection import DetectorError, build_detectors, validate_spans
from ..utils.policy import DEFAULT_POLICY
from ..utils.resolver import resolve_spans
from .data import GroundTruthDocument, load_dataset, load_label_map
from .metrics import DocumentResult, aggregate, evaluate_document


async def evaluate_dataset(
    documents: list[GroundTruthDocument],
    settings: Settings,
    mode: str = "detection",
    include_sensitive_text: bool = False,
    restrict_to_gt_types: bool = False,
    progress: bool = False,
) -> dict:
    detectors = build_detectors(settings)
    results: list[DocumentResult] = []

    # When the ground truth only annotates a subset of PII types (e.g. the
    # LLMAIx set annotates names/IDs/age/DOB but no addresses or phones),
    # counting our correct address redactions as false positives is unfair.
    # This restricts scoring to predicted spans of GT-annotated types.
    gt_types = {entity.entity_type for document in documents for entity in document.entities}

    for index, document in enumerate(documents, start=1):
        started = time.perf_counter()
        all_spans = []
        warnings = list(document.warnings)
        for detector in detectors:
            outcome = await detector.detect(document.text)
            valid, span_warnings = validate_spans(document.text, outcome.spans)
            all_spans.extend(valid)
            warnings.extend(outcome.warnings)
            warnings.extend(span_warnings)
        resolved, _ = resolve_spans(all_spans)

        if mode == "redaction":
            resolved = [
                span
                for span in resolved
                if DEFAULT_POLICY.get(span.entity_type) != TransformationType.PRESERVE
            ]
        if restrict_to_gt_types:
            resolved = [span for span in resolved if span.entity_type in gt_types]
        pred_spans = [(span.start, span.end) for span in resolved]
        processing_ms = (time.perf_counter() - started) * 1000

        result = evaluate_document(
            document.document_id,
            document.text,
            document.entities,
            pred_spans,
            processing_ms=processing_ms,
            warnings=warnings,
        )
        if include_sensitive_text:
            for missed in result.missed_entities:
                missed["text"] = document.text[missed["start"] : missed["end"]]
        results.append(result)
        if progress:
            status = "LEAKED" if result.leaked else "clean"
            print(
                f"[{index}/{len(documents)}] {result.document_id}: {status}, "
                f"char recall {result.chars.recall:.3f} ({processing_ms:.0f} ms)",
                file=sys.stderr,
            )

    return {
        "config": {
            "mode": mode,
            "detectors": settings.detector_names,
            "llm_model": settings.LLM_MODEL if "llm" in settings.detector_names else None,
            "includes_sensitive_text": include_sensitive_text,
            "restrict_to_gt_types": restrict_to_gt_types,
        },
        "aggregate": aggregate(results),
        "documents": [
            {
                "document_id": r.document_id,
                "leaked": r.leaked,
                "chars": r.chars.as_dict(),
                "spans_exact": r.spans_exact.as_dict(),
                "spans_overlap": r.spans_overlap.as_dict(),
                "per_type": r.per_type,
                "missed_entities": r.missed_entities,
                "warnings": r.warnings,
                "processing_ms": round(r.processing_ms, 1),
            }
            for r in results
        ],
    }


def print_summary(report: dict) -> None:
    agg = report["aggregate"]
    leakage = agg["leakage"]
    micro = agg["micro"]
    print()
    print("=" * 62)
    print(f"Documents evaluated:        {agg['documents']}")
    print(
        f"DOCUMENT-LEVEL LEAKAGE:     {leakage['documents_with_leaked_chars']} document(s) "
        f"with leaked characters ({leakage['leakage_rate']:.1%})"
    )
    print(f"  leaked characters total:  {leakage['total_leaked_chars']}")
    print(f"  missed entities total:    {leakage['total_missed_entities']}")
    print("-" * 62)
    chars = micro["chars"]
    print(
        f"Char-level (micro):         P {chars['precision']:.4f}  "
        f"R {chars['recall']:.4f}  F1 {chars['f1']:.4f}"
    )
    overlap = micro["spans_overlap"]
    exact = micro["spans_exact"]
    print(
        f"Span overlap (micro):       P {overlap['precision']:.4f}  "
        f"R {overlap['recall']:.4f}  F1 {overlap['f1']:.4f}"
    )
    print(
        f"Span exact (micro):         P {exact['precision']:.4f}  "
        f"R {exact['recall']:.4f}  F1 {exact['f1']:.4f}"
    )
    print("-" * 62)
    print("Per entity type (GT):       entities  detected  overlap recall")
    for type_name, stats in sorted(agg["per_type"].items()):
        print(
            f"  {type_name:<24} {stats['entities']:>8} {stats['detected_overlap']:>9} "
            f"{stats['span_recall_overlap']:>14.4f}"
        )
    print("=" * 62)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, type=Path, help="JSONL / CAS JSON / dir / zip")
    parser.add_argument("--output", required=True, type=Path, help="Report JSON output path")
    parser.add_argument("--mode", choices=["detection", "redaction"], default="detection")
    parser.add_argument("--detectors", help="Override DETECTORS, e.g. 'rules,llm'")
    parser.add_argument(
        "--label-map", type=Path, help="JSON file mapping annotation labels to entity types"
    )
    parser.add_argument(
        "--include-sensitive-text",
        action="store_true",
        help="Include literal missed-entity text in the report (SENSITIVE — for debugging only)",
    )
    parser.add_argument(
        "--restrict-to-gt-types",
        action="store_true",
        help="Score only predicted spans whose type is annotated in the ground truth "
        "(fair precision when the GT covers a subset of PII types)",
    )
    args = parser.parse_args(argv)

    if args.detectors:
        settings = Settings(DETECTORS=args.detectors)
    else:
        settings = get_settings()

    label_map = load_label_map(args.label_map) if args.label_map else None
    documents = load_dataset(args.input, label_map)
    if not documents:
        print("No documents found in input.", file=sys.stderr)
        return 1
    print(
        f"Evaluating {len(documents)} document(s) with detectors "
        f"{settings.detector_names} in mode '{args.mode}' ...",
        file=sys.stderr,
    )
    if args.include_sensitive_text:
        print(
            "WARNING: the report will contain literal entity text (sensitive).",
            file=sys.stderr,
        )

    try:
        report = asyncio.run(
            evaluate_dataset(
                documents,
                settings,
                mode=args.mode,
                include_sensitive_text=args.include_sensitive_text,
                restrict_to_gt_types=args.restrict_to_gt_types,
                progress=True,
            )
        )
    except DetectorError as exc:
        print(f"Detector error: {exc}", file=sys.stderr)
        return 2

    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report written to {args.output}", file=sys.stderr)
    print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
