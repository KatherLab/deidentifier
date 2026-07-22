"""Error handlers that never leak document content or stack traces.

FastAPI's default RequestValidationError response echoes the invalid input
back to the client — for this application that could be document text, so it
is replaced with a generic message.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..utils.safe_logging import get_safe_logger

logger = get_safe_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "Invalid request."})

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_error",
            error_type=type(exc).__name__,
            path=request.url.path,
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})
