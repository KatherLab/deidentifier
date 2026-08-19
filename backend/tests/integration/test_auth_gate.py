"""The sign-in gate through the real app.

Two things have to hold: with no gate configured the app is exactly what it
was before (principle: the default deployment is unchanged), and with one
configured *nothing* that touches a document answers without a session.
"""

import pytest
from fastapi.testclient import TestClient

from backend.src.core.config import get_settings
from backend.src.services import oidc_client
from backend.src.utils.auth import SESSION_COOKIE, AuthenticatedUser

ISSUER = "https://idp.example.org"
PUBLIC_URL = "http://deid.example.org"
SESSION_SECRET = "0" * 64

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
    "end_session_endpoint": f"{ISSUER}/logout",
}

USER = AuthenticatedUser(subject="idp|42", name="Dr. Müller", email="mueller@example.org")


@pytest.fixture()
def gated_client(monkeypatch):
    """A TestClient for an app with the OIDC gate switched on."""
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "deidentifier")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("OIDC_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("APP_PUBLIC_URL", PUBLIC_URL)
    get_settings.cache_clear()
    oidc_client.reset_caches()

    async def fake_discover(_settings):
        return DISCOVERY

    monkeypatch.setattr(oidc_client, "discover", fake_discover)

    from backend.src.main import app

    with TestClient(app, follow_redirects=False) as client:
        yield client
    get_settings.cache_clear()
    oidc_client.reset_caches()


def sign_in(client: TestClient, monkeypatch) -> None:
    """Walk the real login → callback flow, with only the provider faked.

    Seeding the cookie by hand would be shorter, but then nothing would check
    that the callback issues a cookie the gate actually accepts.
    """

    async def fake_exchange(_settings, _discovery, *, code, verifier):
        assert code == "the-code"
        assert verifier  # the PKCE verifier travelled in the signed state
        return {"id_token": "id", "access_token": "at"}

    async def fake_verify(_settings, _discovery, *, id_token, nonce):
        assert nonce  # bound to this login
        return {"sub": USER.subject, "name": USER.name, "email": USER.email}

    monkeypatch.setattr(oidc_client, "exchange_code", fake_exchange)
    monkeypatch.setattr(oidc_client, "verify_id_token", fake_verify)

    state = client.get("/api/v1/auth/login").cookies["deid_login_state"]
    response = client.get("/api/v1/auth/callback", params={"code": "the-code", "state": state})
    assert response.status_code == 302
    assert response.headers["location"] == f"{PUBLIC_URL}/"


# ── No gate configured: nothing changes ───────────────────────────────────


def test_without_a_gate_the_api_is_open(client):
    assert client.get("/api/v1/status").status_code == 200


def test_without_a_gate_the_session_route_says_so(client):
    body = client.get("/api/v1/auth/session").json()
    assert body == {"enabled": False, "authenticated": True, "user": None, "login_url": ""}


def test_without_a_gate_there_is_nothing_to_sign_in_to(client):
    assert client.get("/api/v1/auth/login").status_code == 404
    assert client.post("/api/v1/auth/logout").status_code == 404


# ── Gate configured ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/status"),
        ("post", "/api/v1/anonymize"),
        ("post", "/api/v1/anonymize/stream"),
        ("post", "/api/v1/export/pdf"),
        ("delete", "/api/v1/anonymize/some-request-id"),
    ],
)
def test_every_document_route_needs_a_session(gated_client, method, path):
    response = getattr(gated_client, method)(path)
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
    assert response.headers["cache-control"] == "no-store"


def test_health_probes_stay_open(gated_client):
    """A readiness probe has no browser and no cookie."""
    assert gated_client.get("/health/live").status_code == 200
    assert gated_client.get("/health/ready").status_code in (200, 503)


def test_a_signed_in_request_passes_the_gate(gated_client, monkeypatch):
    sign_in(gated_client, monkeypatch)
    assert gated_client.get("/api/v1/status").status_code == 200


def test_a_forged_session_cookie_does_not_pass_the_gate(gated_client):
    gated_client.cookies.set(SESSION_COOKIE, "clearly.not.signed")
    assert gated_client.get("/api/v1/status").status_code == 401


def test_the_session_route_reports_who_is_signed_in(gated_client, monkeypatch):
    anonymous = gated_client.get("/api/v1/auth/session").json()
    assert anonymous["enabled"] is True
    assert anonymous["authenticated"] is False
    assert anonymous["login_url"] == f"{PUBLIC_URL}/api/v1/auth/login"

    sign_in(gated_client, monkeypatch)
    signed_in = gated_client.get("/api/v1/auth/session").json()
    assert signed_in["authenticated"] is True
    assert signed_in["user"] == {"name": "Dr. Müller", "email": "mueller@example.org"}


# ── The sign-in flow ──────────────────────────────────────────────────────


def test_login_redirects_to_the_provider_and_remembers_the_state(gated_client):
    response = gated_client.get("/api/v1/auth/login")
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{ISSUER}/authorize?")
    assert "code_challenge_method=S256" in location

    state_cookie = response.cookies.get("deid_login_state")
    assert state_cookie is not None
    # The state in the URL and the state in the cookie must be the same token:
    # that pairing is what makes a callback from elsewhere unusable.
    assert f"state={state_cookie}" in location.replace("%2E", ".")


def test_a_callback_without_the_state_cookie_is_refused(gated_client):
    response = gated_client.get("/api/v1/auth/callback", params={"code": "c", "state": "s"})
    assert response.status_code == 302
    assert response.headers["location"] == f"{PUBLIC_URL}/?auth_error=state"
    assert SESSION_COOKIE not in response.cookies


def test_a_cancelled_sign_in_comes_back_as_denied(gated_client):
    response = gated_client.get("/api/v1/auth/callback", params={"error": "access_denied"})
    assert response.headers["location"] == f"{PUBLIC_URL}/?auth_error=denied"


def test_a_complete_sign_in_issues_a_session(gated_client, monkeypatch):
    sign_in(gated_client, monkeypatch)
    # The gate now lets the document routes through, and the header can say who.
    assert gated_client.get("/api/v1/status").status_code == 200
    assert gated_client.get("/api/v1/auth/session").json()["user"]["name"] == USER.name


def test_a_callback_whose_state_was_not_issued_here_is_refused(gated_client, monkeypatch):
    """A login started against another deployment must not complete here."""
    import jwt

    foreign_state = jwt.encode(
        {"iss": "deidentifier-login", "exp": 4102444800, "verifier": "v", "nonce": "n"},
        "1" * 64,
        algorithm="HS256",
    )
    gated_client.cookies.set("deid_login_state", foreign_state)
    response = gated_client.get(
        "/api/v1/auth/callback", params={"code": "c", "state": foreign_state}
    )
    assert response.headers["location"] == f"{PUBLIC_URL}/?auth_error=state"


def test_logout_drops_the_session(gated_client, monkeypatch):
    sign_in(gated_client, monkeypatch)
    response = gated_client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"redirect_url": None}
    assert gated_client.get("/api/v1/status").status_code == 401


def test_logout_can_end_the_provider_session_too(gated_client, monkeypatch):
    monkeypatch.setenv("OIDC_END_SESSION", "true")
    get_settings.cache_clear()
    sign_in(gated_client, monkeypatch)
    redirect_url = gated_client.post("/api/v1/auth/logout").json()["redirect_url"]
    assert redirect_url.startswith(f"{ISSUER}/logout?")
