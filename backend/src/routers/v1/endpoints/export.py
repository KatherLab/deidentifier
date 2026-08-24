"""Redacted-PDF export.

The client re-sends the original file (nothing is persisted server-side) plus
the request_id from a previous anonymization and the current overrides. When
the file hash matches the cached detection, no OCR or LLM detection is
repeated; otherwise the full pipeline runs first.

Native PDFs are rasterized with exact char-box blackout; scanned PDFs are
rebuilt from the anonymized text at the OCR layout positions. Both paths fail
closed — an export that cannot be verified is refused. The single exception is
a finding the anonymized *text* download carries too (a passage the reviewer
kept that also occurs in redacted form): that one is refused with
`forceable: true` and exported only after the reviewer confirms it."""

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError
from starlette.datastructures import UploadFile

from ....core.config import Settings, get_settings
from ....schemas.anonymize import (
    AnonymizeResponse,
    EntityOverride,
    PdfPagesResponse,
    RedactArea,
)
from ....schemas.entities import EntityType, TransformationType
from ....utils.cache import request_cache
from ....utils.detection import DetectorError
from ....utils.extraction import ExtractionError, LayoutLine, extract_document
from ....utils.ocr_profiles import OcrProfileError, resolve_vision_ocr_profile
from ....utils.pdf_export import (
    ExportError,
    rebuild_scanned_pdf,
    redact_native_pdf,
    render_pdf_pages,
)
from ....utils.pipeline import rerun_with_overrides, run_anonymization
from ....utils.policy import EXPORT_FILENAMES
from ....utils.safe_logging import get_safe_logger, log_reference

router = APIRouter()
logger = get_safe_logger(__name__)

_OVERRIDES_ADAPTER = TypeAdapter(list[EntityOverride])
_POLICY_ADAPTER = TypeAdapter(dict[EntityType, TransformationType])
_AREAS_ADAPTER = TypeAdapter(list[RedactArea])
_MAX_REDACT_AREAS = 200


def _parse_areas(raw) -> list[RedactArea]:
    """User-drawn blackout regions (JSON list in the `redact_areas` field)."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        payload = json.loads(raw)
        if not isinstance(payload, list) or len(payload) > _MAX_REDACT_AREAS:
            raise ValueError
        return _AREAS_ADAPTER.validate_python(payload)
    except (json.JSONDecodeError, ValidationError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid 'redact_areas' payload.") from None


async def _read_pdf_upload(form, settings: Settings) -> bytes:
    """Validate + read the re-sent original PDF (shared by the export routes)."""
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(status_code=400, detail="Multipart field 'file' is required.")
    if not (upload.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=415, detail="Redacted-PDF export is available for PDF uploads only."
        )
    data = await upload.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413, detail=f"File exceeds the {settings.APP_MAX_UPLOAD_MB} MB limit."
        )
    return data


def _parse_bool(raw) -> bool:
    """Parse a multipart boolean flag; accepts 'true'/'1'/'yes'/'on'."""
    return isinstance(raw, str) and raw.strip().lower() in {"true", "1", "yes", "on"}


def _parse_terms(raw) -> list[str] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
        if not isinstance(payload, list) or len(payload) > 100:
            raise ValueError
        terms = [str(term)[:200] for term in payload if str(term).strip()]
        return terms or None
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid terms payload.") from None


def _export_error_response(exc: ExportError) -> JSONResponse:
    """A refused export, as a body the UI can act on.

    `detail` stays the English sentence every other error route returns, so an
    older client keeps showing something sensible; `code` and `forceable` are
    what tells the review UI whether to offer "export anyway", and `items` are
    the passages that would stay visible so the confirmation can name them —
    up to a display cap, which is why `count` is reported separately. They are
    document content and go to the client only — never to a log."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": str(exc),
            "code": exc.code,
            "forceable": exc.forceable,
            "items": exc.items,
            "count": exc.count,
        },
    )


@router.post("/export/pdf")
async def export_pdf(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Response:
    form = await request.form()
    data = await _read_pdf_upload(form, settings)

    overrides: list[EntityOverride] = []
    raw_overrides = form.get("overrides")
    if isinstance(raw_overrides, str) and raw_overrides.strip():
        try:
            overrides = _OVERRIDES_ADAPTER.validate_python(json.loads(raw_overrides))
        except (json.JSONDecodeError, ValidationError):
            raise HTTPException(status_code=422, detail="Invalid 'overrides' payload.") from None

    policy = None
    raw_policy = form.get("policy")
    if isinstance(raw_policy, str) and raw_policy.strip():
        try:
            policy = _POLICY_ADAPTER.validate_python(json.loads(raw_policy))
        except (json.JSONDecodeError, ValidationError):
            raise HTTPException(status_code=422, detail="Invalid 'policy' payload.") from None

    custom_instruction = form.get("custom_instruction")
    if not isinstance(custom_instruction, str) or not custom_instruction.strip():
        custom_instruction = None
    redact_terms = _parse_terms(form.get("redact_terms"))
    preserve_terms = _parse_terms(form.get("preserve_terms"))
    redact_areas = _parse_areas(form.get("redact_areas"))
    raw_language = form.get("output_language")
    output_language = raw_language.strip() if isinstance(raw_language, str) else None
    force_ocr = _parse_bool(form.get("force_ocr"))
    # Scanned documents only: black bars over the placeholders of the rebuilt
    # page, so a reconstruction looks like the native export instead of reading
    # its replacements out in words.
    redaction_bars = _parse_bool(form.get("redaction_bars"))
    # The reviewer confirmed a refused export whose only finding is that a
    # redacted string also occurs outside the redacted passages — i.e. the PDF
    # would show exactly what the anonymized text download already shows.
    # Ignored by every other check; nothing else can be waved through.
    force_export = _parse_bool(form.get("force_export"))
    raw_profile = form.get("ocr_profile")
    ocr_profile = (
        raw_profile.strip() if isinstance(raw_profile, str) and raw_profile.strip() else None
    )
    try:
        # Re-sent by the client (like force_ocr) so a cache-miss re-extraction
        # runs the same OCR configuration the reviewed document came from.
        settings = resolve_vision_ocr_profile(settings, ocr_profile)
    except OcrProfileError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None

    file_hash = hashlib.sha256(data).hexdigest()
    request_id = form.get("request_id")
    result, layout, page_count, source_type = await _detect(
        data,
        file_hash,
        request_id if isinstance(request_id, str) else None,
        overrides,
        policy,
        custom_instruction,
        redact_terms,
        preserve_terms,
        output_language,
        settings,
        force_ocr,
    )

    try:
        if source_type == "pdf":
            pdf_bytes = redact_native_pdf(
                data,
                result.entities,
                settings,
                areas=redact_areas,
                expected_text=result.anonymized_text,
                force=force_export,
            )
        elif source_type == "pdf-ocr":
            pdf_bytes = rebuild_scanned_pdf(
                result.source_text,
                layout,
                result.entities,
                page_count,
                areas=redact_areas,
                bars=redaction_bars,
                expected_text=result.anonymized_text,
                force=force_export,
            )
        else:
            raise HTTPException(
                status_code=415, detail="Redacted-PDF export is available for PDF uploads only."
            )
    except ExportError as exc:
        return _export_error_response(exc)

    logger.info(
        "export_pdf",
        ref=log_reference(result.request_id),
        source_type=source_type,
        entities=len(result.entities),
        areas=len(redact_areas),
        forced=force_export,
        size=len(pdf_bytes),
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{EXPORT_FILENAMES[result.output_language]}.pdf"'
            )
        },
    )


@router.post("/export/pdf/pages", response_model=PdfPagesResponse)
async def export_pdf_pages(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> PdfPagesResponse:
    """Render the pages of a (re-sent) PDF as PNGs for the area-redaction
    editor, including embedded-image bounding boxes as one-click suggestions.
    Nothing is persisted server-side."""
    form = await request.form()
    data = await _read_pdf_upload(form, settings)
    try:
        pages, truncated = render_pdf_pages(data)
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    logger.info("export_pdf_pages", pages=len(pages), truncated=truncated)
    return PdfPagesResponse.model_validate({"pages": pages, "truncated": truncated})


async def _detect(
    data: bytes,
    file_hash: str,
    request_id: str | None,
    overrides: list[EntityOverride],
    policy,
    custom_instruction: str | None,
    redact_terms: list[str] | None,
    preserve_terms: list[str] | None,
    output_language: str | None,
    settings: Settings,
    force_ocr: bool = False,
) -> tuple[AnonymizeResponse, list[LayoutLine], int, str]:
    """Reuse cached detection when the file matches; otherwise run the full
    pipeline (extraction incl. OCR + detection)."""
    if request_id:
        entry = request_cache.get(request_id)
        if entry is not None and entry.file_sha256 == file_hash:
            result = await rerun_with_overrides(
                request_id,
                overrides,
                policy=policy,
                preserve_terms=preserve_terms,
                output_language=output_language,
            )
            if result is not None:
                return result, entry.layout, entry.page_count, entry.source_type

    try:
        extracted = await extract_document(data, "export.pdf", settings, force_ocr=force_ocr)
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    try:
        result = await run_anonymization(
            extracted.text,
            settings,
            extracted.source_type,
            extraction_warnings=extracted.warnings,
            overrides=overrides,
            policy=policy,
            custom_instruction=custom_instruction,
            redact_terms=redact_terms,
            preserve_terms=preserve_terms,
            output_language=output_language,
            file_sha256=file_hash,
            layout=extracted.layout,
            page_count=len(extracted.pages),
        )
    except DetectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    # That run cached its detection under a fresh id the client never learns
    # (an export returns PDF bytes, not JSON), so the entry is unreachable —
    # it could only sit there holding the document text until its TTL ran out.
    request_cache.discard(result.request_id)
    return result, extracted.layout, len(extracted.pages), extracted.source_type
