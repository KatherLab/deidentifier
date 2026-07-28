"""Redacted-PDF export.

The client re-sends the original file (nothing is persisted server-side) plus
the request_id from a previous anonymization and the current overrides. When
the file hash matches the cached detection, no OCR or LLM detection is
repeated; otherwise the full pipeline runs first.

Native PDFs are rasterized with exact char-box blackout; scanned PDFs are
rebuilt from the anonymized text at the OCR layout positions. Both paths fail
closed — an export that cannot be verified is refused."""

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import TypeAdapter, ValidationError
from starlette.datastructures import UploadFile

from ....core.config import Settings, get_settings
from ....schemas.anonymize import AnonymizeResponse, EntityOverride
from ....utils.cache import request_cache
from ....utils.detection import DetectorError
from ....utils.extraction import ExtractionError, LayoutLine, extract_document
from ....utils.pdf_export import (
    ExportError,
    rebuild_scanned_pdf,
    redact_native_pdf,
)
from ....utils.pipeline import rerun_with_overrides, run_anonymization
from ....utils.safe_logging import get_safe_logger

router = APIRouter()
logger = get_safe_logger(__name__)

_OVERRIDES_ADAPTER = TypeAdapter(list[EntityOverride])


@router.post("/export/pdf")
async def export_pdf(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Response:
    form = await request.form()
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

    overrides: list[EntityOverride] = []
    raw_overrides = form.get("overrides")
    if isinstance(raw_overrides, str) and raw_overrides.strip():
        try:
            overrides = _OVERRIDES_ADAPTER.validate_python(json.loads(raw_overrides))
        except (json.JSONDecodeError, ValidationError):
            raise HTTPException(status_code=422, detail="Invalid 'overrides' payload.") from None

    file_hash = hashlib.sha256(data).hexdigest()
    request_id = form.get("request_id")
    result, layout, page_count, source_type = await _detect(
        data, file_hash, request_id if isinstance(request_id, str) else None, overrides, settings
    )

    try:
        if source_type == "pdf":
            pdf_bytes = redact_native_pdf(data, result.entities, settings)
        elif source_type == "pdf-ocr":
            pdf_bytes = rebuild_scanned_pdf(result.source_text, layout, result.entities, page_count)
        else:
            raise HTTPException(
                status_code=415, detail="Redacted-PDF export is available for PDF uploads only."
            )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None

    logger.info(
        "export_pdf",
        request_id=result.request_id,
        source_type=source_type,
        entities=len(result.entities),
        size=len(pdf_bytes),
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="anonymisiert.pdf"'},
    )


async def _detect(
    data: bytes,
    file_hash: str,
    request_id: str | None,
    overrides: list[EntityOverride],
    settings: Settings,
) -> tuple[AnonymizeResponse, list[LayoutLine], int, str]:
    """Reuse cached detection when the file matches; otherwise run the full
    pipeline (extraction incl. OCR + detection)."""
    if request_id:
        entry = request_cache.get(request_id)
        if entry is not None and entry.file_sha256 == file_hash:
            result = await rerun_with_overrides(request_id, overrides)
            if result is not None:
                return result, entry.layout, entry.page_count, entry.source_type

    try:
        extracted = await extract_document(data, "export.pdf", settings)
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    try:
        result = await run_anonymization(
            extracted.text,
            settings,
            extracted.source_type,
            extraction_warnings=extracted.warnings,
            overrides=overrides,
            file_sha256=file_hash,
            layout=extracted.layout,
            page_count=len(extracted.pages),
        )
    except DetectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    return result, extracted.layout, len(extracted.pages), extracted.source_type
