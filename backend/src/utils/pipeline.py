"""End-to-end anonymization pipeline: detect → resolve → transform → validate.

Detection results are cached in memory (short TTL) under the request ID so
review-UI overrides can re-run the cheap deterministic stages without
repeating LLM detection. The LLM re-check of the output runs on full runs
only; override re-runs carry an INFO note instead of repeating it.
"""

import time
import uuid

from ..core.config import Settings
from ..schemas.anonymize import AnonymizeResponse, CacheLifetime, EntityOverride, TimingMs
from ..schemas.entities import (
    EntitySpan,
    EntityType,
    Notice,
    OutputLanguage,
    ValidationResult,
    ValidationSeverity,
    ValidationWarning,
)
from .cache import CachedDetection, request_cache
from .detection import build_detectors, validate_spans
from .leakage import compute_status, validate_output
from .notices import (
    LLM_RECHECK_SKIPPED,
    MANUAL_SELECTION_IGNORED,
    PDF_PRESERVE_NOT_HONOURED,
    notice,
    validation_warning,
)

# Only for the predicate describing what true redaction will black out;
# pymupdf itself is imported lazily inside that module's export functions.
from .pdf_export import preserved_texts_at_risk
from .policy import merge_policy, resolve_output_language
from .resolver import resolve_spans
from .transformation import apply_policy


async def run_anonymization(
    text: str,
    settings: Settings,
    source_type: str,
    extraction_ms: float = 0.0,
    extraction_warnings: list[Notice] | None = None,
    overrides: list[EntityOverride] | None = None,
    policy=None,
    custom_instruction: str | None = None,
    redact_terms: list[str] | None = None,
    preserve_terms: list[str] | None = None,
    output_language: OutputLanguage | str | None = None,
    file_sha256: str | None = None,
    layout: list | None = None,
    page_count: int = 0,
    progress=None,
) -> AnonymizeResponse:
    """Full run: detection, resolution, transformation, validation."""
    language = resolve_output_language(output_language)
    t0 = time.perf_counter()
    detectors = build_detectors(
        settings,
        custom_instruction=custom_instruction,
        redact_terms=redact_terms,
        progress=progress,
    )
    all_spans: list[EntitySpan] = []
    detection_warnings: list[Notice] = []
    for detector in detectors:
        outcome = await detector.detect(text)
        valid, span_warnings = validate_spans(text, outcome.spans)
        all_spans.extend(valid)
        detection_warnings.extend(outcome.warnings)
        detection_warnings.extend(span_warnings)
    detection_ms = (time.perf_counter() - t0) * 1000

    recheck_enabled = "llm" in settings.detector_names and settings.LLM_RECHECK_ENABLED
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
            llm_recheck_performed=recheck_enabled,
            output_language=language,
            file_sha256=file_sha256,
            layout=list(layout or []),
            page_count=page_count,
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
        policy=policy,
        preserve_terms=preserve_terms,
        output_language=language,
        extraction_ms=extraction_ms,
        detection_ms=detection_ms,
        recheck_settings=settings if recheck_enabled else None,
        recheck_skipped_note=False,
        progress=progress,
    )


async def rerun_with_overrides(
    request_id: str,
    overrides: list[EntityOverride],
    policy=None,
    preserve_terms: list[str] | None = None,
    output_language: OutputLanguage | str | None = None,
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
        policy=policy,
        preserve_terms=preserve_terms,
        # A re-run that does not state a language keeps the one the cached
        # document was written in.
        output_language=output_language or entry.output_language,
        extraction_ms=0.0,
        detection_ms=0.0,
        recheck_settings=None,
        recheck_skipped_note=entry.llm_recheck_performed,
        progress=None,
    )


async def _finalize(
    *,
    request_id: str,
    text: str,
    source_type: str,
    resolved: list[EntitySpan],
    warnings: list[Notice],
    detector_warnings: list[Notice],
    overrides: list[EntityOverride] | None,
    policy,
    preserve_terms: list[str] | None,
    output_language: OutputLanguage | str | None,
    extraction_ms: float,
    detection_ms: float,
    recheck_settings: Settings | None,
    recheck_skipped_note: bool,
    progress=None,
) -> AnonymizeResponse:
    active_policy = merge_policy(policy)
    language = resolve_output_language(output_language)
    t1 = time.perf_counter()
    manual_spans, manual_warnings = _manual_spans(text, resolved, overrides)
    if manual_spans:
        resolved, _ = resolve_spans(resolved + manual_spans)
    anonymized, applied, override_warnings = apply_policy(
        text,
        resolved,
        policy=active_policy,
        overrides=overrides,
        preserve_terms=preserve_terms,
        output_language=language,
    )
    override_warnings = manual_warnings + override_warnings
    # The redacted PDF locates text by searching for it, so keeping ONE of
    # several identical passages cannot show through there — say so rather than
    # letting the PDF and the text export disagree in silence. Native PDFs
    # only: the scanned reconstruction applies replacements by offset.
    if source_type == "pdf":
        at_risk = preserved_texts_at_risk(applied)
        if at_risk:
            override_warnings = override_warnings + [
                notice(PDF_PRESERVE_NOT_HONOURED, count=len(at_risk))
            ]
    t2 = time.perf_counter()
    validation = await validate_output(
        anonymized, applied, policy=active_policy, detector_warnings=detector_warnings
    )

    extra_warnings: list[ValidationWarning] = []
    if recheck_settings is not None:
        from .llm_detection import recheck_output

        extra_warnings = await recheck_output(
            anonymized,
            recheck_settings,
            policy=active_policy,
            output_language=language,
            progress=progress,
        )
    elif recheck_skipped_note:
        extra_warnings = [
            validation_warning(
                LLM_RECHECK_SKIPPED,
                category="llm_recheck",
                severity=ValidationSeverity.INFO,
            )
        ]
    if extra_warnings:
        all_warnings = validation.warnings + extra_warnings
        validation = ValidationResult(status=compute_status(all_warnings), warnings=all_warnings)
    t3 = time.perf_counter()

    # Reported so the review UI can show how long the result stays available.
    # An entry the export path already discarded reports "gone" rather than a
    # countdown nobody can act on.
    expires_in, can_extend = request_cache.lifetime(request_id) or (0, False)

    return AnonymizeResponse(
        request_id=request_id,
        source_type=source_type,
        output_language=language,
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
        lifetime=CacheLifetime(expires_in_seconds=expires_in, can_extend=can_extend),
    )


def _manual_spans(
    text: str,
    resolved: list[EntitySpan],
    overrides: list[EntityOverride] | None,
) -> tuple[list[EntitySpan], list[Notice]]:
    """Overrides that match no detected span are user-defined manual
    selections from the review UI: they become first-class spans (validated
    against the source, then merged through the regular overlap resolution).
    The override itself then matches the new span and carries the chosen
    transformation."""
    existing = {(span.start, span.end) for span in resolved}
    spans: list[EntitySpan] = []
    warnings: list[Notice] = []
    for override in overrides or []:
        if (override.start, override.end) in existing:
            continue
        if override.end <= len(text) and text[override.start : override.end] == override.text:
            spans.append(
                EntitySpan(
                    start=override.start,
                    end=override.end,
                    text=override.text,
                    entity_type=override.entity_type or EntityType.OTHER_PII,
                    confidence=1.0,
                    detector="user_manual",
                    metadata={"user_manual": True},
                )
            )
        else:
            warnings.append(notice(MANUAL_SELECTION_IGNORED))
    return spans, warnings
