"""Deterministic merging and overlap resolution of detected spans.

Rules (v1): exact duplicates merge; for identical offsets with conflicting
types the higher-confidence detection wins; for partial overlaps the longer
span wins. Only one transformation may ever apply to a character. Every
conflict produces a traceable decision record.
"""

from pydantic import BaseModel, Field

from ..schemas.entities import EntitySpan


class ResolutionDecision(BaseModel):
    selected: EntitySpan
    rejected: list[EntitySpan] = Field(default_factory=list)
    reason: str


def resolve_spans(
    spans: list[EntitySpan],
) -> tuple[list[EntitySpan], list[ResolutionDecision]]:
    if not spans:
        return [], []
    # Earlier start first; at equal start the longer span first, then higher confidence.
    ordered = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), -s.confidence))
    selected: list[EntitySpan] = [ordered[0]]
    decisions: list[ResolutionDecision] = []

    for span in ordered[1:]:
        current = selected[-1]
        if span.start >= current.end:
            selected.append(span)
            continue
        if span.start == current.start and span.end == current.end:
            if span.entity_type == current.entity_type:
                merged = current.model_copy(
                    update={
                        "confidence": max(current.confidence, span.confidence),
                        "metadata": {
                            **current.metadata,
                            "supporting_detectors": ",".join(
                                sorted({current.detector, span.detector})
                            ),
                        },
                    }
                )
                selected[-1] = merged
                decisions.append(
                    ResolutionDecision(
                        selected=merged, rejected=[span], reason="duplicate span merged"
                    )
                )
            elif span.confidence > current.confidence:
                selected[-1] = span
                decisions.append(
                    ResolutionDecision(
                        selected=span,
                        rejected=[current],
                        reason="identical offsets, higher-confidence type kept",
                    )
                )
            else:
                decisions.append(
                    ResolutionDecision(
                        selected=current,
                        rejected=[span],
                        reason="identical offsets, higher-confidence type kept",
                    )
                )
        else:
            # Contained or partially overlapping: the sort order guarantees the
            # already-selected span starts earlier (or is longer at equal start).
            decisions.append(
                ResolutionDecision(
                    selected=current,
                    rejected=[span],
                    reason="overlapping span, longer/earlier span kept",
                )
            )
    return selected, decisions
