"""Application entrypoint. Run from the repo root:

uv run uvicorn backend.src.main:app --reload --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings, validate_production_settings
from .middleware.error_handlers import register_error_handlers
from .middleware.security_headers import SecurityHeadersMiddleware
from .routers.v1.api import api_router
from .routers.v1.endpoints.health import health_router
from .utils.cache import request_cache
from .utils.safe_logging import get_safe_logger

logging.basicConfig(level=logging.INFO)
logger = get_safe_logger(__name__)

#: How often the expired-entry sweep runs. Without it, eviction would only
#: happen on the next request — an idle process would hold the last documents
#: it saw well past their TTL.
CACHE_SWEEP_INTERVAL_SECONDS = 60


async def _sweep_cache_periodically() -> None:
    while True:
        await asyncio.sleep(CACHE_SWEEP_INTERVAL_SECONDS)
        removed = request_cache.sweep()
        if removed:
            logger.info("cache_swept", removed=removed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_production_settings(settings)
    if settings.APP_ALLOW_INSECURE_CONTENT_LOGGING:
        logger.warning(
            "insecure_content_logging_enabled",
            note="DOCUMENT CONTENT MAY APPEAR IN LOGS - development use only",
        )
    request_cache.configure(settings)
    logger.info(
        "startup",
        env=settings.APP_ENV,
        detectors=settings.DETECTORS,
        result_ttl_minutes=settings.RESULT_CACHE_TTL_MINUTES,
        result_max_lifetime_minutes=settings.RESULT_CACHE_MAX_LIFETIME_MINUTES,
    )
    sweeper = asyncio.create_task(_sweep_cache_periodically())
    try:
        yield
    finally:
        sweeper.cancel()
        await asyncio.gather(sweeper, return_exceptions=True)
        # Nothing outlives the process, and nothing waits for a TTL either.
        request_cache.clear()


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
