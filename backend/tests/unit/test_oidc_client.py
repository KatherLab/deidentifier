"""id_token verification against a provider's JWKS.

This is the one step that decides *who* is signed in, so it is exercised with
a real RSA key pair and real signatures rather than a stubbed decoder.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.src.core.config import Settings
from backend.src.services import oidc_client
from backend.src.services.oidc_client import OidcError

ISSUER = "https://idp.example.org"
CLIENT_ID = "deidentifier"
NONCE = "the-one-nonce"

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
    "userinfo_endpoint": f"{ISSUER}/userinfo",
}


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        OIDC_ENABLED=True,
        OIDC_ISSUER=ISSUER,
        OIDC_CLIENT_ID=CLIENT_ID,
        OIDC_CLIENT_SECRET="s3cret",
        OIDC_SESSION_SECRET="0" * 64,
        APP_PUBLIC_URL="https://deid.example.org",
    )


@pytest.fixture()
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _clear_caches():
    oidc_client.reset_caches()
    yield
    oidc_client.reset_caches()


@pytest.fixture()
def jwks(monkeypatch, signing_key):
    """Serve the public half of `signing_key` as the provider's key set."""
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "key-1", "use": "sig", "alg": "RS256"})
    document = {"keys": [public_jwk]}

    async def fake_fetch(_settings, _uri):
        fake_fetch.calls += 1
        return document

    fake_fetch.calls = 0
    monkeypatch.setattr(oidc_client, "_fetch_jwks", fake_fetch)
    return fake_fetch


def make_id_token(signing_key, *, kid="key-1", **overrides) -> str:
    claims = {
        "iss": ISSUER,
        "sub": "idp|42",
        "aud": CLIENT_ID,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "nonce": NONCE,
        "name": "Dr. Müller",
        "email": "mueller@example.org",
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": kid})


async def test_a_valid_id_token_yields_its_claims(settings, signing_key, jwks):
    claims = await oidc_client.verify_id_token(
        settings, DISCOVERY, id_token=make_id_token(signing_key), nonce=NONCE
    )
    assert claims["sub"] == "idp|42"
    assert claims["email"] == "mueller@example.org"


async def test_a_token_for_another_client_is_rejected(settings, signing_key, jwks):
    token = make_id_token(signing_key, aud="some-other-app")
    with pytest.raises(OidcError, match="verification failed"):
        await oidc_client.verify_id_token(settings, DISCOVERY, id_token=token, nonce=NONCE)


async def test_a_token_from_another_issuer_is_rejected(settings, signing_key, jwks):
    token = make_id_token(signing_key, iss="https://evil.example.org")
    with pytest.raises(OidcError, match="verification failed"):
        await oidc_client.verify_id_token(settings, DISCOVERY, id_token=token, nonce=NONCE)


async def test_an_expired_token_is_rejected(settings, signing_key, jwks):
    token = make_id_token(signing_key, exp=datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(OidcError, match="verification failed"):
        await oidc_client.verify_id_token(settings, DISCOVERY, id_token=token, nonce=NONCE)


async def test_a_token_signed_by_a_stranger_is_rejected(settings, signing_key, jwks):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_id_token(other)
    with pytest.raises(OidcError, match="verification failed"):
        await oidc_client.verify_id_token(settings, DISCOVERY, id_token=token, nonce=NONCE)


async def test_a_token_from_a_different_login_is_rejected(settings, signing_key, jwks):
    """The nonce binds the token to the login this process started."""
    token = make_id_token(signing_key, nonce="replayed-from-elsewhere")
    with pytest.raises(OidcError, match="nonce"):
        await oidc_client.verify_id_token(settings, DISCOVERY, id_token=token, nonce=NONCE)


async def test_an_unsigned_token_is_rejected(settings, signing_key, jwks):
    """`alg: none` must not be an accepted way to sign in."""
    token = jwt.encode({"iss": ISSUER, "sub": "x", "aud": CLIENT_ID}, None, algorithm="none")
    with pytest.raises(OidcError):
        await oidc_client.verify_id_token(settings, DISCOVERY, id_token=token, nonce=NONCE)


async def test_the_key_set_is_fetched_once_then_cached(settings, signing_key, jwks):
    for _ in range(3):
        await oidc_client.verify_id_token(
            settings, DISCOVERY, id_token=make_id_token(signing_key), nonce=NONCE
        )
    assert jwks.calls == 1


async def test_an_unknown_key_id_refetches_the_key_set(settings, signing_key, jwks):
    """What a key rotation looks like — it must not need a restart."""
    await oidc_client.verify_id_token(
        settings, DISCOVERY, id_token=make_id_token(signing_key), nonce=NONCE
    )
    with pytest.raises(OidcError, match="no signing key"):
        await oidc_client.verify_id_token(
            settings, DISCOVERY, id_token=make_id_token(signing_key, kid="key-2"), nonce=NONCE
        )
    assert jwks.calls == 2


# ── Authorization request ─────────────────────────────────────────────────


def test_the_authorize_url_carries_pkce_and_the_registered_redirect(settings):
    url = oidc_client.authorization_url(
        settings, DISCOVERY, state="the-state", nonce=NONCE, code_challenge="chal"
    )
    assert url.startswith(f"{ISSUER}/authorize?")
    for expected in (
        "response_type=code",
        "code_challenge=chal",
        "code_challenge_method=S256",
        "state=the-state",
        "redirect_uri=https%3A%2F%2Fdeid.example.org%2Fapi%2Fv1%2Fauth%2Fcallback",
        "scope=openid+profile+email",
    ):
        assert expected in url


def test_an_authorize_endpoint_with_a_query_string_is_extended_not_broken(settings):
    discovery = DISCOVERY | {"authorization_endpoint": f"{ISSUER}/authorize?tenant=klinik"}
    url = oidc_client.authorization_url(
        settings, discovery, state="s", nonce=NONCE, code_challenge="c"
    )
    assert "?tenant=klinik&response_type=code" in url


def test_a_discovery_document_without_an_authorize_endpoint_is_refused(settings):
    with pytest.raises(OidcError, match="authorization_endpoint"):
        oidc_client.authorization_url(settings, {}, state="s", nonce=NONCE, code_challenge="c")


def test_basic_auth_is_used_only_when_the_provider_offers_nothing_else():
    assert oidc_client._prefers_basic_auth({}) is False
    assert (
        oidc_client._prefers_basic_auth(
            {"token_endpoint_auth_methods_supported": ["client_secret_basic"]}
        )
        is True
    )
    assert (
        oidc_client._prefers_basic_auth(
            {"token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"]}
        )
        is False
    )


def test_end_session_url_is_none_when_the_provider_has_no_such_endpoint(settings):
    assert oidc_client.end_session_url(settings, DISCOVERY) is None
    url = oidc_client.end_session_url(
        settings, DISCOVERY | {"end_session_endpoint": f"{ISSUER}/out"}
    )
    assert url is not None
    assert url.startswith(f"{ISSUER}/out?")
    assert "post_logout_redirect_uri=https%3A%2F%2Fdeid.example.org" in url
