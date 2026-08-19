"""OpenID Connect client for the optional sign-in gate.

Authorization Code flow with PKCE against the operator-configured provider:
discovery, the authorize URL, the code exchange, id_token verification against
the provider's JWKS, and the optional userinfo lookup.

The issuer is **operator configuration, not user input** — nobody can point
this at an address of their choosing through the API — so the endpoints named
in the discovery document are taken at face value beyond a scheme check.
Everything else follows the repo's outbound-HTTP rules: explicit timeouts, no
redirect following, and errors that never echo the provider's response body.
"""

from urllib.parse import urlencode

import httpx
import jwt

from ..core.config import Settings
from ..utils.safe_logging import get_safe_logger

logger = get_safe_logger(__name__)

#: The signature algorithms an id_token may use. Symmetric algorithms are
#: absent on purpose: accepting HS256 here would let anyone who knows the
#: client secret mint tokens, and `none` needs no explanation.
_ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256"]

#: Per-process caches. Discovery documents and signing keys are effectively
#: static; a restart re-reads them, and a key rotation is picked up by the
#: unknown-`kid` refresh in `_signing_key`.
_discovery_cache: dict[str, dict] = {}
_jwks_cache: dict[str, dict] = {}


class OidcError(Exception):
    """A sign-in could not be completed. `code` is a stable, translatable
    reason the frontend shows; `message` is for the log, not the browser."""

    def __init__(self, message: str, *, code: str = "provider", status_code: int = 502):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def reset_caches() -> None:
    """Forget the cached discovery document and keys (tests, config reload)."""
    _discovery_cache.clear()
    _jwks_cache.clear()


def _client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.OIDC_HTTP_TIMEOUT_SECONDS,
        follow_redirects=False,
    )


def _require_absolute(url: object, field: str) -> str:
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        raise OidcError(f"discovery document has no usable {field}", code="provider")
    return url


async def discover(settings: Settings) -> dict:
    """The provider's discovery document, fetched once per process."""
    issuer = settings.oidc_issuer
    cached = _discovery_cache.get(issuer)
    if cached is not None:
        return cached

    url = f"{issuer}/.well-known/openid-configuration"
    try:
        async with _client(settings) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        # The raw error can name the internal address the issuer resolved to.
        logger.warning("oidc_discovery_unreachable", issuer=issuer, error=type(exc).__name__)
        raise OidcError("discovery endpoint unreachable", code="provider") from exc
    if response.status_code != 200:
        logger.warning("oidc_discovery_failed", issuer=issuer, status=response.status_code)
        raise OidcError("discovery endpoint returned an error", code="provider")
    try:
        document = response.json()
    except ValueError as exc:
        raise OidcError("discovery endpoint returned no JSON", code="provider") from exc
    if not isinstance(document, dict):
        raise OidcError("discovery endpoint returned no JSON object", code="provider")

    _require_absolute(document.get("authorization_endpoint"), "authorization_endpoint")
    _require_absolute(document.get("token_endpoint"), "token_endpoint")
    _discovery_cache[issuer] = document
    return document


def authorization_url(
    settings: Settings,
    discovery: dict,
    *,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    endpoint = _require_absolute(discovery.get("authorization_endpoint"), "authorization_endpoint")
    params = {
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode(params)}"


async def exchange_code(settings: Settings, discovery: dict, *, code: str, verifier: str) -> dict:
    """Trade the authorization code for the token response."""
    endpoint = _require_absolute(discovery.get("token_endpoint"), "token_endpoint")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.OIDC_CLIENT_ID,
        "code_verifier": verifier,
    }
    auth: tuple[str, str] | None = None
    if _prefers_basic_auth(discovery):
        auth = (settings.OIDC_CLIENT_ID, settings.OIDC_CLIENT_SECRET)
    else:
        data["client_secret"] = settings.OIDC_CLIENT_SECRET

    try:
        async with _client(settings) as client:
            response = await client.post(endpoint, data=data, auth=auth)
    except httpx.HTTPError as exc:
        logger.warning("oidc_token_unreachable", error=type(exc).__name__)
        raise OidcError("token endpoint unreachable", code="token") from exc
    if response.status_code != 200:
        # The body can carry the client secret back at us in an error echo.
        logger.warning("oidc_token_exchange_failed", status=response.status_code)
        raise OidcError("token exchange failed", code="token", status_code=400)
    try:
        payload = response.json()
    except ValueError as exc:
        raise OidcError("token endpoint returned no JSON", code="token") from exc
    if not isinstance(payload, dict) or not payload.get("id_token"):
        raise OidcError("token response carried no id_token", code="token")
    return payload


def _prefers_basic_auth(discovery: dict) -> bool:
    """HTTP Basic when the provider advertises it *and* not the POST form.

    Both are mandatory-to-implement in the spec but real providers implement
    one or the other, and picking the wrong one fails with an opaque 401.
    """
    methods = discovery.get("token_endpoint_auth_methods_supported")
    if not isinstance(methods, list):
        return False
    return "client_secret_basic" in methods and "client_secret_post" not in methods


def _match_key(jwks: dict, kid: str | None) -> object | None:
    try:
        key_set = jwt.PyJWKSet.from_dict(jwks)
    except jwt.exceptions.PyJWKSetError as exc:
        raise OidcError("provider returned an unusable JWKS", code="identity") from exc
    for key in key_set.keys:
        if key.public_key_use not in (None, "sig"):
            continue
        if kid is None or key.key_id == kid:
            return key.key
    return None


async def _signing_key(settings: Settings, discovery: dict, id_token: str) -> object:
    jwks_uri = _require_absolute(discovery.get("jwks_uri"), "jwks_uri")
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
    except jwt.PyJWTError as exc:
        raise OidcError("id_token has no readable header", code="identity") from exc

    cached = _jwks_cache.get(jwks_uri)
    if cached is not None:
        key = _match_key(cached, kid)
        if key is not None:
            return key
        # An unknown `kid` is what a key rotation looks like. Refusing every
        # sign-in until the next restart is not an acceptable answer to it.
    jwks = await _fetch_jwks(settings, jwks_uri)
    _jwks_cache[jwks_uri] = jwks
    key = _match_key(jwks, kid)
    if key is None:
        raise OidcError("no signing key matches the id_token", code="identity")
    return key


async def _fetch_jwks(settings: Settings, jwks_uri: str) -> dict:
    try:
        async with _client(settings) as client:
            response = await client.get(jwks_uri)
    except httpx.HTTPError as exc:
        logger.warning("oidc_jwks_unreachable", error=type(exc).__name__)
        raise OidcError("jwks endpoint unreachable", code="identity") from exc
    if response.status_code != 200:
        raise OidcError("jwks endpoint returned an error", code="identity")
    try:
        jwks = response.json()
    except ValueError as exc:
        raise OidcError("jwks endpoint returned no JSON", code="identity") from exc
    if not isinstance(jwks, dict):
        raise OidcError("jwks endpoint returned no JSON object", code="identity")
    return jwks


async def verify_id_token(
    settings: Settings, discovery: dict, *, id_token: str, nonce: str
) -> dict:
    """Verify signature, issuer, audience, expiry and the nonce binding.

    The nonce check is what makes a stolen or replayed id_token useless: it was
    minted for one login attempt whose state cookie this process signed.
    """
    key = await _signing_key(settings, discovery, id_token)
    issuer = discovery.get("issuer") or settings.oidc_issuer
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=_ID_TOKEN_ALGORITHMS,
            audience=settings.OIDC_CLIENT_ID,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("oidc_id_token_rejected", error=type(exc).__name__)
        raise OidcError("id_token verification failed", code="identity") from exc
    if claims.get("nonce") != nonce:
        raise OidcError("id_token nonce does not match this login", code="identity")
    return claims


async def fetch_userinfo(settings: Settings, discovery: dict, *, access_token: str) -> dict:
    """Best-effort display details. A provider that omits `name`/`email` from
    the id_token usually serves them here; a failure is not a failed sign-in."""
    endpoint = discovery.get("userinfo_endpoint")
    if not isinstance(endpoint, str) or not endpoint.lower().startswith(("http://", "https://")):
        return {}
    try:
        async with _client(settings) as client:
            response = await client.get(
                endpoint, headers={"Authorization": f"Bearer {access_token}"}
            )
    except httpx.HTTPError:
        logger.warning("oidc_userinfo_unreachable")
        return {}
    if response.status_code != 200:
        logger.warning("oidc_userinfo_failed", status=response.status_code)
        return {}
    try:
        info = response.json()
    except ValueError:
        return {}
    return info if isinstance(info, dict) else {}


def end_session_url(settings: Settings, discovery: dict) -> str | None:
    """The provider's RP-initiated logout URL, or None when it has none.

    No `id_token_hint`: keeping the id_token around only to hand it back at
    sign-out would mean carrying it in the session cookie for the whole shift.
    `client_id` + `post_logout_redirect_uri` is the spec's alternative.
    """
    endpoint = discovery.get("end_session_endpoint")
    if not isinstance(endpoint, str) or not endpoint.lower().startswith(("http://", "https://")):
        return None
    params = urlencode(
        {
            "client_id": settings.OIDC_CLIENT_ID,
            "post_logout_redirect_uri": settings.public_url or "/",
        }
    )
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{params}"
