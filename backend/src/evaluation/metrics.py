"""Evaluation metrics.

Character-level semantics follow LLMAIx's report-redaction evaluation so
results stay comparable: every character position is classified
redacted/not-redacted, the positive class is "redacted" (a false negative is a
leaked character), and whitespace/punctuation positions are excluded from
scoring. On top of that: span-level exact/overlap metrics, a per-entity-type
breakdown, and document-level leakage as the headline number.
"""

from dataclasses import dataclass, field

from .data import GroundTruthEntity

# LLMAIx parity set, extended with \t and \r.
NON_SCORED_CHARS = set(" ,.!?:;-()\"'\n\t\r")

Span = tuple[int, int]


@dataclass
class CharMetrics:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def specificity(self) -> float:
        return self.tn / (self.tn + self.fp) if (self.tn + self.fp) else 0.0

    def add(self, other: "CharMetrics") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.tn += other.tn
        self.fn += other.fn

    def as_dict(self) -> dict:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "specificity": round(self.specificity, 4),
        }


@dataclass
class SpanMetrics:
    gt_total: int = 0
    gt_matched: int = 0
    pred_total: int = 0
    pred_matched: int = 0

    @property
    def recall(self) -> float:
        return self.gt_matched / self.gt_total if self.gt_total else 0.0

    @property
    def precision(self) -> float:
        return self.pred_matched / self.pred_total if self.pred_total else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def add(self, other: "SpanMetrics") -> None:
        self.gt_total += other.gt_total
        self.gt_matched += other.gt_matched
        self.pred_total += other.pred_total
        self.pred_matched += other.pred_matched

    def as_dict(self) -> dict:
        return {
            "gt_total": self.gt_total,
            "gt_matched": self.gt_matched,
            "pred_total": self.pred_total,
            "pred_matched": self.pred_matched,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


@dataclass
class DocumentResult:
    document_id: str
    chars: CharMetrics
    spans_exact: SpanMetrics
    spans_overlap: SpanMetrics
    per_type: dict[str, dict]
    missed_entities: list[dict]  # offsets + type only; literal text is opt-in
    leaked: bool
    processing_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)


def char_confusion(text: str, gt_spans: list[Span], pred_spans: list[Span]) -> CharMetrics:
    gt_mask = _mask(len(text), gt_spans)
    pred_mask = _mask(len(text), pred_spans)
    metrics = CharMetrics()
    for char, gt, pred in zip(text, gt_mask, pred_mask):
        if char in NON_SCORED_CHARS:
            continue
        if gt and pred:
            metrics.tp += 1
        elif not gt and pred:
            metrics.fp += 1
        elif gt and not pred:
            metrics.fn += 1
        else:
            metrics.tn += 1
    return metrics


def span_metrics(gt_spans: list[Span], pred_spans: list[Span], *, exact: bool) -> SpanMetrics:
    def matches(a: Span, b: Span) -> bool:
        if exact:
            return a == b
        return a[0] < b[1] and b[0] < a[1]  # any overlap

    metrics = SpanMetrics(gt_total=len(gt_spans), pred_total=len(pred_spans))
    metrics.gt_matched = sum(1 for g in gt_spans if any(matches(g, p) for p in pred_spans))
    metrics.pred_matched = sum(1 for p in pred_spans if any(matches(p, g) for g in gt_spans))
    return metrics


def evaluate_document(
    document_id: str,
    text: str,
    gt_entities: list[GroundTruthEntity],
    pred_spans: list[Span],
    processing_ms: float = 0.0,
    warnings: list[str] | None = None,
) -> DocumentResult:
    gt_spans = [(e.start, e.end) for e in gt_entities]
    chars = char_confusion(text, gt_spans, pred_spans)

    per_type: dict[str, dict] = {}
    for entity_type in sorted({e.entity_type for e in gt_entities}):
        typed = [e for e in gt_entities if e.entity_type == entity_type]
        typed_spans = [(e.start, e.end) for e in typed]
        typed_chars = char_confusion(text, typed_spans, pred_spans)
        overlap = span_metrics(typed_spans, pred_spans, exact=False)
        per_type[entity_type.value] = {
            "entities": len(typed),
            "detected_overlap": overlap.gt_matched,
            "span_recall_overlap": round(overlap.recall, 4),
            "char_recall": round(typed_chars.recall, 4),
        }

    missed = [
        {"start": e.start, "end": e.end, "entity_type": e.entity_type.value, "label": e.label}
        for e in gt_entities
        if not any(e.start < p[1] and p[0] < e.end for p in pred_spans)
    ]

    return DocumentResult(
        document_id=document_id,
        chars=chars,
        spans_exact=span_metrics(gt_spans, pred_spans, exact=True),
        spans_overlap=span_metrics(gt_spans, pred_spans, exact=False),
        per_type=per_type,
        missed_entities=missed,
        leaked=chars.fn > 0,
        processing_ms=processing_ms,
        warnings=list(warnings or []),
    )


def aggregate(results: list[DocumentResult]) -> dict:
    micro_chars = CharMetrics()
    micro_exact = SpanMetrics()
    micro_overlap = SpanMetrics()
    per_type_totals: dict[str, dict] = {}
    for result in results:
        micro_chars.add(result.chars)
        micro_exact.add(result.spans_exact)
        micro_overlap.add(result.spans_overlap)
        for type_name, stats in result.per_type.items():
            bucket = per_type_totals.setdefault(type_name, {"entities": 0, "detected_overlap": 0})
            bucket["entities"] += stats["entities"]
            bucket["detected_overlap"] += stats["detected_overlap"]
    for stats in per_type_totals.values():
        stats["span_recall_overlap"] = (
            round(stats["detected_overlap"] / stats["entities"], 4) if stats["entities"] else 0.0
        )

    count = len(results)
    leaked_documents = sum(1 for r in results if r.leaked)
    macro = {
        "char_precision": _mean([r.chars.precision for r in results]),
        "char_recall": _mean([r.chars.recall for r in results]),
        "char_f1": _mean([r.chars.f1 for r in results]),
        "span_overlap_recall": _mean([r.spans_overlap.recall for r in results]),
    }
    return {
        "documents": count,
        # Document-level leakage is the headline number: aggregate F1 can look
        # excellent while individual documents still leak identifiers.
        "leakage": {
            "documents_with_leaked_chars": leaked_documents,
            "documents_clean": count - leaked_documents,
            "leakage_rate": round(leaked_documents / count, 4) if count else 0.0,
            "total_leaked_chars": micro_chars.fn,
            "total_missed_entities": sum(len(r.missed_entities) for r in results),
        },
        "micro": {
            "chars": micro_chars.as_dict(),
            "spans_exact": micro_exact.as_dict(),
            "spans_overlap": micro_overlap.as_dict(),
        },
        "macro": {key: round(value, 4) for key, value in macro.items()},
        "per_type": per_type_totals,
        "mean_processing_ms": _mean([r.processing_ms for r in results]),
    }


def _mask(length: int, spans: list[Span]) -> list[bool]:
    mask = [False] * length
    for start, end in spans:
        for index in range(max(start, 0), min(end, length)):
            mask[index] = True
    return mask


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0
