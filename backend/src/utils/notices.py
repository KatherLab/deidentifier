"""Stable codes + English text for every non-fatal message the pipeline emits.

Warnings used to be free-form English strings that the German UI rendered
verbatim. They now carry a stable `code` and its `params`, so the frontend can
show them in the user's language (`frontend/locales/*.json`, under
`warnings.codes.*`) while the English `message` composed here remains the
fallback for unknown codes and for direct API consumers.

Adding a warning = a constant + an entry in `_MESSAGES` here + the matching
key in every locale catalog (`npm run i18n:check` enforces the parity).
"""

from ..schemas.entities import Notice, ValidationSeverity, ValidationWarning

# --- Extraction ---------------------------------------------------------------

DOCX_COMMENTS = "docx_comments"
DOCX_TRACKED_CHANGES = "docx_tracked_changes"
DOCX_TRACKED_DELETIONS = "docx_tracked_deletions"
DOCX_TEXT_BOXES = "docx_text_boxes"
PDF_NO_PAGE_MAPPING = "pdf_no_page_mapping"
PDF_DOCLING_FALLBACK = "pdf_docling_fallback"
OCR_RECOGNITION_ERRORS = "ocr_recognition_errors"

# --- Detection ----------------------------------------------------------------

LLM_MENTION_NOT_LOCATED = "llm_mention_not_located"
INVALID_SPAN_REJECTED = "invalid_span_rejected"

# --- Transformation / review overrides ----------------------------------------

OVERRIDE_NOT_MATCHED = "override_not_matched"
MANUAL_SELECTION_IGNORED = "manual_selection_ignored"
PDF_PRESERVE_NOT_HONOURED = "pdf_preserve_not_honoured"

# --- Leakage validation -------------------------------------------------------

RESIDUAL_IDENTIFIER = "residual_identifier"
REVALIDATION_HIT = "revalidation_hit"
LABELLED_FIELD = "labelled_field"

# --- LLM re-check -------------------------------------------------------------

LLM_RECHECK_FAILED = "llm_recheck_failed"
LLM_RECHECK_REMAINING = "llm_recheck_remaining"
LLM_RECHECK_UNLOCATED = "llm_recheck_unlocated"
LLM_RECHECK_SKIPPED = "llm_recheck_skipped"
RECHECK_RISK = "recheck_risk"

_MESSAGES: dict[str, str] = {
    DOCX_COMMENTS: "The document contains comments, which are not extracted.",
    DOCX_TRACKED_CHANGES: (
        "The document contains tracked changes; inserted text may be incomplete."
    ),
    DOCX_TRACKED_DELETIONS: ("The document contains tracked deletions, which are not extracted."),
    DOCX_TEXT_BOXES: "The document contains text boxes, which are not extracted.",
    PDF_NO_PAGE_MAPPING: "Page mapping is not available for docling-serve extraction.",
    PDF_DOCLING_FALLBACK: "docling-serve failed ({reason}); used local extraction.",
    OCR_RECOGNITION_ERRORS: "Text was produced by OCR; recognition errors are possible.",
    LLM_MENTION_NOT_LOCATED: (
        "The LLM reported a {entity_type} mention that could not be located in the "
        "source text; please review the document manually."
    ),
    INVALID_SPAN_REJECTED: ("Rejected invalid span from detector '{detector}' (offset mismatch)."),
    OVERRIDE_NOT_MATCHED: "An override did not match any detected span and was ignored.",
    MANUAL_SELECTION_IGNORED: (
        "A manual selection no longer matches the source text and was ignored."
    ),
    PDF_PRESERVE_NOT_HONOURED: (
        "{count} passage(s) you kept also occur elsewhere in redacted form. The "
        "redacted PDF blacks out every occurrence of a redacted text, so these "
        "stay covered there even though the text export keeps them."
    ),
    RESIDUAL_IDENTIFIER: "Redacted {entity_type} content appears to remain in the output.",
    REVALIDATION_HIT: "A rule detector still finds a possible {entity_type} in the output.",
    LABELLED_FIELD: "A labelled field appears to be followed by non-redacted content.",
    LLM_RECHECK_FAILED: (
        "The LLM re-check could not be performed; please review the result manually."
    ),
    LLM_RECHECK_REMAINING: (
        "The LLM re-check found a possible remaining {entity_type} in the output."
    ),
    LLM_RECHECK_UNLOCATED: (
        "The LLM re-check reported possible remaining PII that could not be located."
    ),
    LLM_RECHECK_SKIPPED: "The LLM re-check was not repeated for this adjusted result.",
    RECHECK_RISK: ("The LLM re-check rates the remaining risk of re-identification as {risk}."),
}


def notice(code: str, **params: str | int | float | bool) -> Notice:
    """Build a notice: stable code + its params + the English rendering."""
    return Notice(code=code, message=_MESSAGES[code].format(**params), params=dict(params))


def validation_warning(
    code: str,
    *,
    category: str,
    severity: ValidationSeverity,
    start: int | None = None,
    end: int | None = None,
    **params: str | int | float | bool,
) -> ValidationWarning:
    """A `ValidationWarning` carrying the same translation contract."""
    built = notice(code, **params)
    return ValidationWarning(
        category=category,
        message=built.message,
        severity=severity,
        start=start,
        end=end,
        code=built.code,
        params=built.params,
    )


def warning_from_notice(
    source: Notice,
    *,
    category: str,
    severity: ValidationSeverity,
    start: int | None = None,
    end: int | None = None,
) -> ValidationWarning:
    """Promote an already-built notice (e.g. from a detector) to a warning."""
    return ValidationWarning(
        category=category,
        message=source.message,
        severity=severity,
        start=start,
        end=end,
        code=source.code,
        params=source.params,
    )
