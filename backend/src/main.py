"""Application entrypoint. Run from the repo root:

uv run uvicorn backend.src.main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings, validate_production_settings
from .middleware.error_handlers import register_error_handlers
from .middleware.security_headers import SecurityHeadersMiddleware
from .routers.v1.api import api_router
from .routers.v1.endpoints.health import health_router
from .utils.safe_logging import get_safe_logger

logging.basicConfig(level=logging.INFO)
logger = get_safe_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_production_settings(settings)
    if settings.APP_ALLOW_INSECURE_CONTENT_LOGGING:
        logger.warning(
            "insecure_content_logging_enabled",
            note="DOCUMENT CONTENT MAY APPEAR IN LOGS - development use only",
        )
    logger.info("startup", env=settings.APP_ENV, detectors=settings.DETECTORS)
    yield


_settings = get_settings()
_docs_enabled = _settings.APP_ENV != "production"

app = FastAPI(
    title="Medical Document Anonymizer",
    version=_settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(api_router)
app.include_router(health_router)
