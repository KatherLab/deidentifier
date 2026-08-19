"""The access gate, when one is configured (`OIDC_ENABLED`).

Enforced in middleware rather than as a per-route dependency on purpose: a
route added next month is then gated because it is under `/api/`, not because
somebody remembered to declare it. The only way to *lose* protection is to add
a path to `EXEMPT_PREFIXES` below, which is a visible edit.

`/health/*` stays open — a readiness probe has no browser and no cookie — and
so do the sign-in routes themselves, which are what an unauthenticated caller
is supposed to reach.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..core.config import get_settings
from ..utils.auth import SESSION_COOKIE, read_session

#: Everything under /api/ is gated except these.
EXEMPT_PREFIXES = ("/api/v1/auth/",)


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        path = request.url.path
        gated = (
            settings.OIDC_ENABLED
            and path.startswith("/api/")
            and not path.startswith(EXEMPT_PREFIXES)
        )
        if gated and read_session(settings, request.cookies.get(SESSION_COOKIE)) is None:
            # Short-circuits before SecurityHeadersMiddleware, so the no-store
            # header this response needs is set here.
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
                headers={"Cache-Control": "no-store"},
            )
        return await call_next(request)
