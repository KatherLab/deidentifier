"""End-to-end anonymization pipeline: detect → resolve → transform → validate.

Detection results are cached in memory (short TTL) under the request ID so
review-UI overrides can re-run the cheap deterministic stages without
repeating LLM detection.
"""

import time
import uuid

from ..core.config import Settings
from ..schemas.anonymize import AnonymizeResponse, EntityOverride, TimingMs
from ..schemas.entities import EntitySpan
from .cache import CachedDetection, request_cache
from .detection import build_detectors, validate_spans
from .leakage import validate_output
from .resolver import resolve_spans
from .transformation import apply_policy


async def run_anonymization(
    text: str,
    settings: Settings,
    source_type: str,
    extraction_ms: float = 0.0,
    extraction_warnings: list[str] | None = None,
    overrides: list[EntityOverride] | None = None,
) -> AnonymizeResponse:
    """Full run: detection, resolution, transformation, validation."""
    t0 = time.perf_counter()
    detectors = build_detectors(settings)
    all_spans: list[EntitySpan] = []
    detection_warnings: list[str] = []
    for detector in detectors:
        outcome = await detector.detect(text)
        valid, span_warnings = validate_spans(text, outcome.spans)
        all_spans.extend(valid)
        detection_warnings.extend(outcome.warnings)
        detection_warnings.extend(span_warnings)
    detection_ms = (time.perf_counter() - t0) * 1000

    resolved, _decisions = resolve_spans(all_spans)
    request_id = str(uuid.uuid4())
    request_cache.put(
        request_id,
        CachedDetection(
            text=text,
            source_type=source_type,
            spans=resolved,
            extraction_warnings=list(extraction_warnings or []),
            detection_warnings=detection_warnings,
        ),
    )
    return await _finalize(
        request_id=request_id,
        text=text,
        source_type=source_type,
        resolved=resolved,
        warnings=list(extraction_warnings or []),
        detector_warnings=detection_warnings,
        overrides=overrides,
        extraction_ms=extraction_ms,
        detection_ms=detection_ms,
    )


async def rerun_with_overrides(
    request_id: str,
    overrides: list[EntityOverride],
) -> AnonymizeResponse | None:
    """Re-run transformation + validation from cached detection results.

    Returns None when the cache entry has expired (the caller should ask the
    user to re-run full anonymization).
    """
    entry = request_cache.get(request_id)
    if entry is None:
        return None
    return await _finalize(
        request_id=request_id,
        text=entry.text,
        source_type=entry.source_type,
        resolved=entry.spans,
        warnings=list(entry.extraction_warnings),
        detector_warnings=list(entry.detection_warnings),
        overrides=overrides,
        extraction_ms=0.0,
        detection_ms=0.0,
    )


async def _finalize(
    *,
    request_id: str,
    text: str,
    source_type: str,
    resolved: list[EntitySpan],
    warnings: list[str],
    detector_warnings: list[str],
    overrides: list[EntityOverride] | None,
    extraction_ms: float,
    detection_ms: float,
) -> AnonymizeResponse:
    t1 = time.perf_counter()
    anonymized, applied, override_warnings = apply_policy(text, resolved, overrides=overrides)
    t2 = time.perf_counter()
    validation = await validate_output(anonymized, applied, detector_warnings=detector_warnings)
    t3 = time.perf_counter()

    return AnonymizeResponse(
        request_id=request_id,
        source_type=source_type,
        source_text=text,
        anonymized_text=anonymized,
        entities=applied,
        validation=validation,
        warnings=warnings + override_warnings,
        timing_ms=TimingMs(
            extraction=round(extraction_ms, 2),
            detection=round(detection_ms, 2),
            transformation=round((t2 - t1) * 1000, 2),
            validation=round((t3 - t2) * 1000, 2),
            total=round(extraction_ms + detection_ms + (t3 - t1) * 1000, 2),
        ),
    )
