"""Session and login-state tokens for the optional OIDC gate.

There is no database and no server-side session store, so the signed cookie
*is* the session. Two token kinds, both HS256 over ``OIDC_SESSION_SECRET``:

``session``
    Issued after a successful sign-in. Carries only what the header displays
    (a name, an email) plus the subject the provider issued — never anything
    derived from a document.

``state``
    Issued at the start of the login redirect and valid for ten minutes. It
    carries the PKCE ``code_verifier`` and the ``nonce`` so the flow needs no
    server-side storage, which keeps it correct across restarts and workers.

Both are opaque to the browser in the sense that matters: they are signed, so
a tampered cookie is rejected rather than believed.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from ..core.config import Settings

#: Cookie holding the signed session. HttpOnly + SameSite=Lax: the API is only
#: ever called from the app's own origin, and Lax still sends the cookie on the
#: provider's top-level redirect back to the callback.
SESSION_COOKIE = "deid_session"
#: Cookie holding the login state, cleared as soon as the callback runs. Paired
#: with the `state` query parameter so a forged callback fails the comparison.
STATE_COOKIE = "deid_login_state"
#: How long a started login may take to come back. Ten minutes is long enough
#: for a password + second factor and short enough to be worthless later.
STATE_MAX_AGE_SECONDS = 600

_ALGORITHM = "HS256"
_SESSION_ISSUER = "deidentifier-session"
_STATE_ISSUER = "deidentifier-login"


@dataclass(frozen=True)
class AuthenticatedUser:
    """The whole of what this app knows about who is signed in."""

    subject: str
    name: str
    email: str


@dataclass(frozen=True)
class LoginState:
    code_verifier: str
    nonce: str


def _now() -> datetime:
    return datetime.now(UTC)


def pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for the S256 method."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def issue_state(settings: Settings, *, code_verifier: str, nonce: str) -> str:
    payload = {
        "iss": _STATE_ISSUER,
        "iat": _now(),
        "exp": _now() + timedelta(seconds=STATE_MAX_AGE_SECONDS),
        "verifier": code_verifier,
        "nonce": nonce,
    }
    return jwt.encode(payload, settings.OIDC_SESSION_SECRET, algorithm=_ALGORITHM)


def read_state(settings: Settings, token: str | None) -> LoginState | None:
    """Verify a login-state token. ``None`` for anything not currently valid."""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.OIDC_SESSION_SECRET,
            algorithms=[_ALGORITHM],
            issuer=_STATE_ISSUER,
            options={"require": ["exp", "iss"]},
        )
    except jwt.PyJWTError:
        return None
    verifier = payload.get("verifier")
    nonce = payload.get("nonce")
    if not isinstance(verifier, str) or not isinstance(nonce, str):
        return None
    return LoginState(code_verifier=verifier, nonce=nonce)


def issue_session(settings: Settings, user: AuthenticatedUser) -> str:
    payload = {
        "iss": _SESSION_ISSUER,
        "sub": user.subject,
        "iat": _now(),
        # Absolute, like the result cache's TTL: a session that renewed itself
        # on every request would never end for someone who leaves the tab open.
        "exp": _now() + timedelta(minutes=settings.OIDC_SESSION_MINUTES),
        "name": user.name,
        "email": user.email,
    }
    return jwt.encode(payload, settings.OIDC_SESSION_SECRET, algorithm=_ALGORITHM)


def read_session(settings: Settings, token: str | None) -> AuthenticatedUser | None:
    """Verify a session cookie. ``None`` means "not signed in" — expired,
    tampered with, or signed under a rotated secret are all the same answer."""
    if not token or not settings.OIDC_SESSION_SECRET:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.OIDC_SESSION_SECRET,
            algorithms=[_ALGORITHM],
            issuer=_SESSION_ISSUER,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        return None
    name = payload.get("name")
    email = payload.get("email")
    return AuthenticatedUser(
        subject=subject,
        name=name if isinstance(name, str) else "",
        email=email if isinstance(email, str) else "",
    )
