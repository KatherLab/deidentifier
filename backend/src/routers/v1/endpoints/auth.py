"""The optional OpenID Connect sign-in gate.

Four routes, all exempt from the gate itself (`middleware/auth_gate.py`):

| Route | Purpose |
|---|---|
| `GET /api/v1/auth/session` | Who is signed in — and whether a gate exists at all. The frontend's first call. |
| `GET /api/v1/auth/login` | Top-level redirect to the provider (PKCE + signed state cookie). |
| `GET /api/v1/auth/callback` | The provider returns here; verifies, then sets the session cookie. |
| `POST /api/v1/auth/logout` | Drops the session cookie, optionally ending the provider's session too. |

A failed sign-in redirects back to the app with `?auth_error=<code>` instead of
rendering an API error page: the person in front of it is a clinician who
pressed a button, not a caller reading JSON. The codes are stable and
translated in the frontend catalogs.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ....core.config import Settings, get_settings
from ....schemas.auth import AuthUser, LogoutResponse, SessionResponse
from ....services import oidc_client
from ....services.oidc_client import OidcError
from ....utils.auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    STATE_MAX_AGE_SECONDS,
    AuthenticatedUser,
    issue_session,
    issue_state,
    pkce_pair,
    read_session,
    read_state,
)
from ....utils.safe_logging import get_safe_logger, log_reference

router = APIRouter(prefix="/auth")
logger = get_safe_logger(__name__)

#: The session cookie is only ever sent to the API, so it is scoped to it.
_SESSION_COOKIE_PATH = "/api"
#: The state cookie is needed by exactly one route.
_STATE_COOKIE_PATH = "/api/v1/auth"


def _require_enabled(settings: Settings) -> None:
    if not settings.OIDC_ENABLED:
        raise HTTPException(status_code=404, detail="Sign-in is not configured on this server")


def _app_redirect(settings: Settings, *, auth_error: str | None = None) -> RedirectResponse:
    """Back to the app itself. There is one screen, so there is one target —
    which also means there is no redirect parameter to tamper with."""
    target = f"{settings.public_url}/"
    if auth_error:
        target = f"{target}?auth_error={auth_error}"
    return RedirectResponse(url=target, status_code=302)


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.OIDC_SESSION_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookies_secure,
        path=_SESSION_COOKIE_PATH,
    )


@router.get("/session", response_model=SessionResponse)
async def read_current_session(
    request: Request, settings: Settings = Depends(get_settings)
) -> SessionResponse:
    """The frontend's first call. With no gate configured this reports
    `enabled=false` and the app runs exactly as it did before."""
    if not settings.OIDC_ENABLED:
        return SessionResponse(enabled=False, authenticated=True)
    user = read_session(settings, request.cookies.get(SESSION_COOKIE))
    return SessionResponse(
        enabled=True,
        authenticated=user is not None,
        user=AuthUser(name=user.name, email=user.email) if user else None,
        login_url=f"{settings.public_url}/api/v1/auth/login",
    )


@router.get("/login")
async def login(settings: Settings = Depends(get_settings)) -> Response:
    """Begin the Authorization Code flow."""
    _require_enabled(settings)
    verifier, challenge = pkce_pair()
    nonce = secrets.token_urlsafe(32)
    # The very same token goes into the URL and into the cookie: the callback
    # requires both, so a login started elsewhere cannot be completed here.
    state = issue_state(settings, code_verifier=verifier, nonce=nonce)
    try:
        discovery = await oidc_client.discover(settings)
        url = oidc_client.authorization_url(
            settings, discovery, state=state, nonce=nonce, code_challenge=challenge
        )
    except OidcError as exc:
        logger.warning("oidc_login_start_failed", reason=exc.code)
        return _app_redirect(settings, auth_error=exc.code)

    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookies_secure,
        path=_STATE_COOKIE_PATH,
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
) -> Response:
    """Where the provider sends the browser back."""
    _require_enabled(settings)
    cookie_state = request.cookies.get(STATE_COOKIE)

    def finish(response: Response) -> Response:
        response.delete_cookie(STATE_COOKIE, path=_STATE_COOKIE_PATH)
        return response

    if error:
        # The provider declined — typically the user cancelled at the login
        # screen, so this is a normal outcome, not a fault.
        logger.info("oidc_login_declined", reason=error[:64])
        return finish(_app_redirect(settings, auth_error="denied"))

    if not code or not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        logger.warning("oidc_callback_state_mismatch")
        return finish(_app_redirect(settings, auth_error="state"))
    login_state = read_state(settings, state)
    if login_state is None:
        logger.warning("oidc_callback_state_invalid")
        return finish(_app_redirect(settings, auth_error="state"))

    try:
        discovery = await oidc_client.discover(settings)
        tokens = await oidc_client.exchange_code(
            settings, discovery, code=code, verifier=login_state.code_verifier
        )
        claims = await oidc_client.verify_id_token(
            settings, discovery, id_token=tokens["id_token"], nonce=login_state.nonce
        )
        user = await _user_from_claims(settings, discovery, claims, tokens)
    except OidcError as exc:
        logger.warning("oidc_login_failed", reason=exc.code)
        return finish(_app_redirect(settings, auth_error=exc.code))

    # The subject identifies a person; it is logged only as a correlation
    # handle, like the request id.
    logger.info("oidc_login", subject_ref=log_reference(user.subject))
    response = finish(_app_redirect(settings))
    _set_session_cookie(response, settings, issue_session(settings, user))
    return response


async def _user_from_claims(
    settings: Settings, discovery: dict, claims: dict, tokens: dict
) -> AuthenticatedUser:
    """The display name and email, from the id_token where the provider put
    them there and from userinfo otherwise."""
    name = _first_string(claims, ("name", "preferred_username", "given_name"))
    email = _first_string(claims, ("email",))
    access_token = tokens.get("access_token")
    if not (name and email) and isinstance(access_token, str) and access_token:
        info = await oidc_client.fetch_userinfo(settings, discovery, access_token=access_token)
        name = name or _first_string(info, ("name", "preferred_username", "given_name"))
        email = email or _first_string(info, ("email",))
    return AuthenticatedUser(
        subject=str(claims["sub"]),
        name=name or email,
        email=email,
    )


def _first_string(source: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@router.post("/logout", response_model=LogoutResponse)
async def logout(settings: Settings = Depends(get_settings)) -> Response:
    """Drop the session. Always succeeds, whether or not one existed."""
    _require_enabled(settings)
    redirect_url: str | None = None
    if settings.OIDC_END_SESSION:
        try:
            redirect_url = oidc_client.end_session_url(
                settings, await oidc_client.discover(settings)
            )
        except OidcError:
            # The local session is gone either way; that is the part this app
            # is responsible for.
            logger.warning("oidc_end_session_unavailable")
    response = Response(
        content=LogoutResponse(redirect_url=redirect_url).model_dump_json(),
        media_type="application/json",
    )
    response.delete_cookie(SESSION_COOKIE, path=_SESSION_COOKIE_PATH)
    return response
