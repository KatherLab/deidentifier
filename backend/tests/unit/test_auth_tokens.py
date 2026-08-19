"""Session and login-state cookies: the whole of the gate's server-side state.

There is no session store to fall back on, so these tokens have to be right on
their own — a forged or stale one must read as "not signed in", never as a
default user.
"""

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from backend.src.core.config import Settings, validate_auth_settings
from backend.src.utils.auth import (
    AuthenticatedUser,
    issue_session,
    issue_state,
    pkce_pair,
    read_session,
    read_state,
)

SECRET = "0" * 64


def make_settings(**overrides) -> Settings:
    base = {
        "OIDC_ENABLED": True,
        "OIDC_ISSUER": "https://idp.example.org",
        "OIDC_CLIENT_ID": "deidentifier",
        "OIDC_CLIENT_SECRET": "s3cret",
        "OIDC_SESSION_SECRET": SECRET,
        "APP_PUBLIC_URL": "https://deid.example.org",
    }
    base.update(overrides)
    return Settings(**base)


USER = AuthenticatedUser(subject="idp|42", name="Dr. Müller", email="mueller@example.org")


def test_session_round_trip_preserves_the_identity():
    settings = make_settings()
    user = read_session(settings, issue_session(settings, USER))
    assert user == USER


def test_session_signed_with_another_secret_is_not_a_session():
    token = issue_session(make_settings(), USER)
    assert read_session(make_settings(OIDC_SESSION_SECRET="1" * 64), token) is None


def test_tampered_session_is_rejected():
    token = issue_session(make_settings(), USER)
    header, payload, signature = token.split(".")
    # Swap in a payload claiming a different subject, keeping the signature.
    forged = jwt.encode({"sub": "attacker"}, "1" * 64, algorithm="HS256").split(".")[1]
    assert read_session(make_settings(), f"{header}.{forged}.{signature}") is None


def test_expired_session_is_rejected():
    settings = make_settings()
    expired = jwt.encode(
        {
            "iss": "deidentifier-session",
            "sub": USER.subject,
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        SECRET,
        algorithm="HS256",
    )
    assert read_session(settings, expired) is None


def test_session_lifetime_follows_the_setting():
    settings = make_settings(OIDC_SESSION_MINUTES=30)
    claims = jwt.decode(
        issue_session(settings, USER),
        SECRET,
        algorithms=["HS256"],
        issuer="deidentifier-session",
        audience=None,
    )
    remaining = claims["exp"] - claims["iat"]
    assert remaining == 30 * 60


@pytest.mark.parametrize("token", ["", None, "not-a-jwt", "a.b.c"])
def test_garbage_is_not_a_session(token):
    assert read_session(make_settings(), token) is None


def test_a_state_token_carries_the_verifier_and_nonce():
    settings = make_settings()
    state = issue_state(settings, code_verifier="v" * 43, nonce="n0nce")
    parsed = read_state(settings, state)
    assert parsed is not None
    assert parsed.code_verifier == "v" * 43
    assert parsed.nonce == "n0nce"


def test_a_session_token_is_not_accepted_as_login_state():
    """Distinct issuers: neither token kind may be replayed as the other."""
    settings = make_settings()
    assert read_state(settings, issue_session(settings, USER)) is None
    assert read_session(settings, issue_state(settings, code_verifier="v", nonce="n")) is None


def test_pkce_challenge_is_the_s256_hash_of_the_verifier():
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert challenge == expected.decode().rstrip("=")
    assert pkce_pair()[0] != verifier  # a fresh verifier per login


def test_redirect_uri_is_derived_from_the_public_url():
    settings = make_settings(APP_PUBLIC_URL="https://deid.example.org/")
    assert settings.oidc_redirect_uri == "https://deid.example.org/api/v1/auth/callback"
    assert settings.cookies_secure is True
    assert make_settings(APP_PUBLIC_URL="http://localhost:8080").cookies_secure is False


def test_openid_scope_is_always_requested():
    assert "openid" in make_settings(OIDC_SCOPES="profile email").oidc_scopes.split()


# ── Startup validation ────────────────────────────────────────────────────


def test_a_disabled_gate_needs_no_configuration():
    validate_auth_settings(Settings())


def test_half_configured_gate_refuses_to_start():
    with pytest.raises(RuntimeError, match="OIDC_CLIENT_SECRET"):
        validate_auth_settings(make_settings(OIDC_CLIENT_SECRET=""))


def test_a_short_session_secret_refuses_to_start():
    with pytest.raises(RuntimeError, match="OIDC_SESSION_SECRET"):
        validate_auth_settings(make_settings(OIDC_SESSION_SECRET="short"))


def test_a_relative_public_url_refuses_to_start():
    with pytest.raises(RuntimeError, match="APP_PUBLIC_URL"):
        validate_auth_settings(make_settings(APP_PUBLIC_URL="deid.example.org"))


def test_a_fully_configured_gate_starts():
    validate_auth_settings(make_settings())
