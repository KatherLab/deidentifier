"""Operational status: configured backends and limits. Never returns
filesystem paths, keys, or full endpoint URLs — host and locality only."""

import ipaddress
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from ....core.config import Settings, get_settings
from ....schemas.anonymize import (
    Banner,
    DetectorStatus,
    ExternalEndpoint,
    Limits,
    OcrProfileStatus,
    StatusResponse,
)
from ....utils.detection import detector_ready
from ....utils.ocr_profiles import OcrProfileError, parse_profiles

router = APIRouter()


def _is_local(host: str) -> bool:
    if host in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        # Single-label hostnames (Docker service names like "vllm") count as local.
        return "." not in host


@router.get("/status", response_model=StatusResponse)
async def status(settings: Settings = Depends(get_settings)) -> StatusResponse:
    detectors = [
        DetectorStatus(name=name, enabled=True, ready=detector_ready(name, settings))
        for name in settings.detector_names
    ]
    try:
        profiles = parse_profiles(settings) if settings.OCR_ENGINE == "llm_vision" else []
    except OcrProfileError as exc:
        # A malformed profile list is an operator error; surface it instead of
        # advertising a selection that requests would then refuse.
        raise HTTPException(status_code=500, detail=str(exc)) from None

    candidates = [
        ("llm", settings.OPENAI_API_BASE if "llm" in settings.detector_names else ""),
        ("docling", settings.DOCLING_SERVE_URL if settings.OCR_ENGINE != "none" else ""),
        ("mistral_ocr", settings.MISTRAL_API_BASE if settings.OCR_ENGINE == "mistral_ocr" else ""),
    ]
    if settings.OCR_ENGINE == "llm_vision":
        if profiles:
            # One entry per profile: the banner must be honest about every
            # host a document could be sent to, not only the default's.
            candidates += [
                (f"vision_ocr:{p.name}", p.api_base or settings.VISION_OCR_API_BASE)
                for p in profiles
            ]
        else:
            candidates.append(("vision_ocr", settings.VISION_OCR_API_BASE))
    endpoints = []
    for name, url in candidates:
        if not url:
            continue
        host = urlparse(url).hostname or ""
        endpoints.append(ExternalEndpoint(name=name, host=host, local=_is_local(host)))

    return StatusResponse(
        app_env=settings.APP_ENV,
        version=settings.APP_VERSION,
        detectors=detectors,
        ocr_engine=settings.OCR_ENGINE,
        ocr_dialect=(
            (profiles[0].dialect or settings.VISION_OCR_DIALECT)
            if profiles
            else (settings.VISION_OCR_DIALECT if settings.OCR_ENGINE == "llm_vision" else None)
        ),
        ocr_profiles=[
            OcrProfileStatus(
                name=p.name,
                model=p.model,
                dialect=p.dialect or settings.VISION_OCR_DIALECT,
                default=(index == 0),
            )
            for index, p in enumerate(profiles)
        ],
        external_endpoints=endpoints,
        limits=Limits(
            max_upload_mb=settings.APP_MAX_UPLOAD_MB,
            max_text_chars=settings.APP_MAX_TEXT_CHARS,
        ),
        banner=(
            Banner.model_validate({"text": settings.banner_text, "color": settings.banner_color})
            if settings.banner_active
            else None
        ),
    )
