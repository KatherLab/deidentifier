"""The anonymization endpoint. Accepts pasted text or override re-runs (JSON)
and file uploads (multipart) on the same route, dispatched by content type."""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from ....core.config import Settings, get_settings
from ....schemas.anonymize import AnonymizeResponse, AnonymizeTextRequest
from ....utils.detection import DetectorError
from ....utils.extraction import ExtractionError, extract_document
from ....utils.pipeline import rerun_with_overrides, run_anonymization
from ....utils.safe_logging import get_safe_logger

router = APIRouter()
logger = get_safe_logger(__name__)

_ALLOWED_SUFFIXES = {".txt", ".docx", ".pdf"}


@router.post("/anonymize", response_model=AnonymizeResponse)
async def anonymize(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AnonymizeResponse:
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        response = await _handle_json(request, settings)
    elif content_type.startswith("multipart/form-data"):
        response = await _handle_upload(request, settings)
    else:
        raise HTTPException(
            status_code=415,
            detail="Send application/json with 'text' or multipart/form-data with 'file'.",
        )

    logger.info(
        "anonymize_request",
        request_id=response.request_id,
        source_type=response.source_type,
        chars=len(response.source_text),
        entities=len(response.entities),
        validation=response.validation.status,
        total_ms=response.timing_ms.total,
    )
    return response


async def _handle_json(request: Request, settings: Settings) -> AnonymizeResponse:
    payload = await _parse_json(request)
    return await _process_json(payload, settings)


async def _parse_json(request: Request) -> AnonymizeTextRequest:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from None
    try:
        return AnonymizeTextRequest(**body)
    except (ValidationError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="Provide 'text' (non-empty string) or 'request_id' with 'overrides'.",
        ) from None


async def _process_json(
    payload: AnonymizeTextRequest, settings: Settings, progress=None
) -> AnonymizeResponse:
    # Override re-run from cached detection results.
    if payload.text is None:
        response = await rerun_with_overrides(
            payload.request_id or "",
            payload.overrides,
            policy=payload.policy,
            preserve_terms=payload.preserve_terms,
        )
        if response is None:
            raise HTTPException(
                status_code=410,
                detail="The cached result has expired; please re-run the anonymization.",
            )
        return response

    _check_text_limits(payload.text, settings)
    return await _run(
        payload.text,
        settings,
        "paste",
        overrides=payload.overrides or None,
        policy=payload.policy,
        custom_instruction=payload.custom_instruction,
        redact_terms=payload.redact_terms,
        preserve_terms=payload.preserve_terms,
        progress=progress,
    )


@dataclass
class _UploadInput:
    data: bytes
    filename: str
    policy: dict | None = None
    custom_instruction: str | None = None
    redact_terms: list[str] | None = None
    preserve_terms: list[str] | None = field(default=None)


async def _handle_upload(request: Request, settings: Settings) -> AnonymizeResponse:
    upload_input = await _parse_upload(request, settings)
    return await _process_upload(upload_input, settings)


async def _parse_upload(request: Request, settings: Settings) -> _UploadInput:
    form = await request.form()
    policy = _parse_policy_form(form.get("policy"))
    custom_instruction = form.get("custom_instruction")
    if not isinstance(custom_instruction, str) or not custom_instruction.strip():
        custom_instruction = None
    redact_terms = _parse_terms_form(form.get("redact_terms"))
    preserve_terms = _parse_terms_form(form.get("preserve_terms"))
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(status_code=400, detail="Multipart field 'file' is required.")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415, detail="Unsupported file type; allowed: .txt, .docx, .pdf"
        )
    data = await upload.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.APP_MAX_UPLOAD_MB} MB limit.",
        )
    return _UploadInput(
        data=data,
        filename=upload.filename or "",
        policy=policy,
        custom_instruction=custom_instruction,
        redact_terms=redact_terms,
        preserve_terms=preserve_terms,
    )


async def _process_upload(
    upload_input: _UploadInput, settings: Settings, progress=None
) -> AnonymizeResponse:
    started = time.perf_counter()
    try:
        extracted = await extract_document(
            upload_input.data, upload_input.filename, settings, progress=progress
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    extraction_ms = (time.perf_counter() - started) * 1000

    _check_text_limits(extracted.text, settings)
    return await _run(
        extracted.text,
        settings,
        extracted.source_type,
        extraction_ms=extraction_ms,
        extraction_warnings=extracted.warnings,
        policy=upload_input.policy,
        custom_instruction=upload_input.custom_instruction,
        redact_terms=upload_input.redact_terms,
        preserve_terms=upload_input.preserve_terms,
        file_sha256=hashlib.sha256(upload_input.data).hexdigest(),
        layout=extracted.layout,
        page_count=len(extracted.pages),
        progress=progress,
    )


async def _run(
    text: str,
    settings: Settings,
    source_type: str,
    extraction_ms: float = 0.0,
    extraction_warnings: list[str] | None = None,
    overrides=None,
    policy=None,
    custom_instruction: str | None = None,
    redact_terms: list[str] | None = None,
    preserve_terms: list[str] | None = None,
    file_sha256: str | None = None,
    layout=None,
    page_count: int = 0,
    progress=None,
) -> AnonymizeResponse:
    try:
        return await run_anonymization(
            text,
            settings,
            source_type,
            extraction_ms=extraction_ms,
            extraction_warnings=extraction_warnings,
            overrides=overrides,
            policy=policy,
            custom_instruction=custom_instruction,
            redact_terms=redact_terms,
            preserve_terms=preserve_terms,
            file_sha256=file_sha256,
            layout=layout,
            page_count=page_count,
            progress=progress,
        )
    except DetectorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.post("/anonymize/stream")
async def anonymize_stream(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Like /anonymize, but streams NDJSON progress events followed by the
    result: {"event":"progress","stage":...,"done":n,"total":m} lines, then
    {"event":"result","data":{...}} or {"event":"error","status":...,"detail":...}.
    Inputs are parsed before streaming starts, so malformed requests fail with
    regular HTTP errors. A client disconnect cancels the pipeline."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        payload = await _parse_json(request)

        async def run(progress) -> AnonymizeResponse:
            return await _process_json(payload, settings, progress=progress)
    elif content_type.startswith("multipart/form-data"):
        upload_input = await _parse_upload(request, settings)

        async def run(progress) -> AnonymizeResponse:
            return await _process_upload(upload_input, settings, progress=progress)
    else:
        raise HTTPException(
            status_code=415,
            detail="Send application/json with 'text' or multipart/form-data with 'file'.",
        )

    queue: asyncio.Queue = asyncio.Queue()

    def progress(stage: str, done: int, total: int) -> None:
        queue.put_nowait({"event": "progress", "stage": stage, "done": done, "total": total})

    async def worker() -> None:
        try:
            response = await run(progress)
            await queue.put({"event": "result", "data": response.model_dump(mode="json")})
        except HTTPException as exc:
            await queue.put({"event": "error", "status": exc.status_code, "detail": exc.detail})
        except Exception:
            logger.error("anonymize_stream_failed", error_type="unhandled")
            await queue.put({"event": "error", "status": 500, "detail": "Internal server error."})
        finally:
            await queue.put(None)

    task = asyncio.create_task(worker())

    async def stream():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            # Client disconnect (or completion): stop the pipeline.
            task.cancel()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        # X-Accel-Buffering disables nginx response buffering so progress
        # events reach the browser immediately.
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )


def _parse_policy_form(raw) -> dict | None:
    """Parse the multipart 'policy' field (JSON object) if present."""
    import json

    from pydantic import TypeAdapter

    from ....schemas.entities import EntityType, TransformationType

    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return TypeAdapter(dict[EntityType, TransformationType]).validate_python(json.loads(raw))
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid 'policy' payload.") from None


def _parse_terms_form(raw) -> list[str] | None:
    """Parse a multipart terms field (JSON array of strings) if present."""
    import json

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


def _check_text_limits(text: str, settings: Settings) -> None:
    if len(text) > settings.APP_MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text exceeds the limit of {settings.APP_MAX_TEXT_CHARS} characters.",
        )
    if not text.strip():
        raise HTTPException(status_code=422, detail="The document contains no text.")
