"""Application settings.

Follows the llmaixweb pattern: pydantic-settings, ENV_PATH selects the .env
file, every variable documented in .env.example. No network checks at startup —
backend readiness is reported via /health/ready instead of refusing to boot.
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Colour schemes the frontend banner knows how to render.
BANNER_COLORS = ("amber", "red", "blue", "green", "gray")


def _default_env_file() -> str | None:
    """ENV_PATH wins; otherwise the repo-top .env, then backend/.env."""
    override = os.getenv("ENV_PATH")
    if override:
        path = Path(override)
        return str(path) if path.is_file() else None
    for candidate in (Path(".env"), Path("backend/.env")):
        if candidate.is_file():
            return str(candidate)
    return None


_env_file = _default_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=_env_file,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_ENV: str = "development"
    APP_VERSION: str = "0.3.0"
    APP_MAX_UPLOAD_MB: int = Field(default=20, ge=1)
    APP_MAX_TEXT_CHARS: int = Field(default=500_000, ge=1)
    APP_ALLOW_INSECURE_CONTENT_LOGGING: bool = False
    APP_CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # How long a finished result stays in memory for cheap review-UI re-runs.
    # This is a retention setting, not a performance one: while an entry lives,
    # a copy of the document is in the process's memory. See
    # docs/DATA_RETENTION.md before raising any of the three.
    RESULT_CACHE_TTL_MINUTES: int = Field(default=15, ge=1)
    # What one press of "Verlängern" grants, counted from the moment of the
    # press. Repeatable, so a reviewer who keeps working keeps the result.
    RESULT_CACHE_EXTENSION_MINUTES: int = Field(default=60, ge=1)
    # The ceiling no amount of extending can cross, counted from when the
    # result was produced. 720 minutes = 12 hours (a long shift).
    # Setting this equal to RESULT_CACHE_TTL_MINUTES turns extending off.
    RESULT_CACHE_MAX_LIFETIME_MINUTES: int = Field(default=720, ge=1)
    # How many results may be in memory at once; the oldest is dropped beyond
    # it. Bounds the worst-case amount of document text the process holds.
    RESULT_CACHE_MAX_ENTRIES: int = Field(default=100, ge=1)

    # Deployment banner shown above the header (e.g. "Research Use Only!").
    # The text is operator-authored and displayed verbatim in every interface
    # language — it is a deployment statement, not UI text.
    BANNER_ENABLED: bool = False
    BANNER_TEXT: str = ""
    BANNER_COLOR: str = "amber"  # amber | red | blue | green | gray

    # ── Access control (optional) ──────────────────────────────────────────
    # Off by default: the app is designed to run behind the hospital's own
    # auth proxy. Switching it on makes the app itself require a sign-in at
    # the organisation's OpenID Connect provider. It is a *gate*, not an
    # authorisation model — everyone who can sign in gets the same, whole app.
    OIDC_ENABLED: bool = False
    # Provider base URL; the app reads {issuer}/.well-known/openid-configuration.
    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_SCOPES: str = "openid profile email"
    # Signing key for the session cookie (and the short-lived login state).
    # Rotating it signs everyone out; sharing it is equivalent to sharing
    # every session. Generate with: openssl rand -hex 32
    OIDC_SESSION_SECRET: str = ""
    OIDC_SESSION_MINUTES: int = Field(default=480, ge=5)
    # Also end the session at the provider on sign-out (RP-initiated logout),
    # when the provider advertises an end_session_endpoint. Off by default:
    # it signs the user out of every application, not only this one.
    OIDC_END_SESSION: bool = False
    OIDC_HTTP_TIMEOUT_SECONDS: int = Field(default=10, ge=1)
    # The public origin browsers reach the app at, e.g. https://deid.klinik.de.
    # The redirect URI registered with the provider is derived from it, so it
    # must match what the browser actually uses — not the container's address.
    APP_PUBLIC_URL: str = ""

    # Detectors: comma-separated (mock | rules | llm)
    DETECTORS: str = "rules"

    # Primary PII detection LLM (OpenAI-compatible) — Milestone 2
    OPENAI_API_BASE: str = ""
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_REQUEST_TIMEOUT_SECONDS: int = Field(default=600, ge=1)
    LLM_CHUNK_CHARS: int = Field(default=16000, ge=500)
    LLM_CHUNK_OVERLAP: int = Field(default=500, ge=0)
    # Independent detection passes whose results are unioned (recall-first;
    # counters run-to-run variance of the model).
    LLM_DETECTION_PASSES: int = Field(default=2, ge=1, le=5)
    LLM_MAX_CONCURRENT_REQUESTS: int = Field(default=4, ge=1, le=32)
    # After transformation, ask the LLM whether PII remains in the output
    # (adds warnings, never edits).
    LLM_RECHECK_ENABLED: bool = True

    # Extraction / OCR — Milestone 2
    DOCLING_SERVE_URL: str = ""
    DOCLING_MIN_EXTRACTED_CHARS_PDF: int = Field(default=100, ge=0)
    PDF_MAX_PAGES_FOR_TEXT_PROBE: int = Field(default=5, ge=1)
    OCR_ENGINE: str = "none"  # none | docling_tesseract | mistral_ocr | llm_vision
    MISTRAL_API_BASE: str = ""
    MISTRAL_API_KEY: str = ""
    MISTRAL_OCR_MODEL: str = "mistral-ocr-latest"
    VISION_OCR_API_BASE: str = ""
    VISION_OCR_API_KEY: str = ""
    VISION_OCR_MODEL: str = ""
    # Which model family the endpoint serves — selects the request recipe and
    # the response parser (services/ocr_dialects.py):
    # unlimited_ocr | chandra | plain. An unknown name fails the request
    # loudly; a mis-parsed response would silently drop text.
    VISION_OCR_DIALECT: str = "unlimited_ocr"
    # Optional: several selectable OCR models at once. Raw JSON list of
    # profile objects ({"name", "model", "dialect", ...}); unset fields
    # inherit the flat VISION_OCR_* values, the first entry is the default.
    # Empty = feature off, the flat settings are the only configuration.
    # See utils/ocr_profiles.py and docs/operations/ocr-engines.md.
    VISION_OCR_PROFILES: str = ""
    # The four recipe values below default to unset = "use the dialect's
    # default". Setting one overrides the dialect for every model.
    VISION_OCR_PROMPT: str | None = None
    # Retry prompt for a page that the primary prompt transcribes to (near-)
    # empty text while the rendered page clearly has ink. Explicitly empty
    # disables the fallback.
    VISION_OCR_FALLBACK_PROMPT: str | None = None
    VISION_OCR_MAX_TOKENS: int | None = Field(default=None, ge=256)
    # Raw JSON merged into the request body (e.g. Unlimited-OCR's
    # skip_special_tokens / vllm_xargs); "{}" sends none.
    VISION_OCR_EXTRA_BODY: str | None = None
    VISION_OCR_TIMEOUT_SECONDS: int = Field(default=600, ge=1)
    VISION_OCR_MAX_CONCURRENT_PAGES: int = Field(default=2, ge=1, le=16)
    # Page render scale: 1.0 = 72 dpi; 2.8 ≈ 200 dpi.
    VISION_OCR_RENDER_SCALE: float = Field(default=2.8, ge=1.0, le=6.0)

    @property
    def detector_names(self) -> list[str]:
        return [d.strip() for d in self.DETECTORS.split(",") if d.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.APP_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.APP_MAX_UPLOAD_MB * 1024 * 1024

    @property
    def banner_text(self) -> str:
        return self.BANNER_TEXT.strip()

    @property
    def banner_color(self) -> str:
        """An unrecognized colour name falls back to amber — a typo here must
        not keep the deployment from starting."""
        color = self.BANNER_COLOR.strip().lower()
        return color if color in BANNER_COLORS else "amber"

    @property
    def banner_active(self) -> bool:
        """Enabled *and* non-empty — an empty banner would be a blank bar."""
        return self.BANNER_ENABLED and bool(self.banner_text)

    @property
    def public_url(self) -> str:
        return self.APP_PUBLIC_URL.strip().rstrip("/")

    @property
    def oidc_issuer(self) -> str:
        return self.OIDC_ISSUER.strip().rstrip("/")

    @property
    def oidc_scopes(self) -> str:
        """The requested scopes, always including `openid` — without it the
        provider runs a plain OAuth flow and returns no id_token."""
        scopes = self.OIDC_SCOPES.split()
        if "openid" not in scopes:
            scopes.insert(0, "openid")
        return " ".join(scopes)

    @property
    def oidc_redirect_uri(self) -> str:
        """The callback URL that must be registered with the provider."""
        return f"{self.public_url}/api/v1/auth/callback"

    @property
    def cookies_secure(self) -> bool:
        """`Secure` on the session cookie whenever the app is served over TLS.
        An http:// deployment cannot set it without breaking sign-in."""
        return self.public_url.lower().startswith("https://")


#: A shorter key than this makes the session cookie's signature guessable.
MIN_SESSION_SECRET_CHARS = 32


def validate_auth_settings(settings: Settings) -> None:
    """Refuse to start with a half-configured OIDC gate.

    Checked in every environment, not only production: an access gate that
    silently does not gate is worse than one that never came up. The counterpart
    — the app running with no gate at all — is the documented default, so an
    operator cannot reach this state by accident.
    """
    if not settings.OIDC_ENABLED:
        return
    problems: list[str] = []
    required = {
        "OIDC_ISSUER": settings.oidc_issuer,
        "OIDC_CLIENT_ID": settings.OIDC_CLIENT_ID.strip(),
        "OIDC_CLIENT_SECRET": settings.OIDC_CLIENT_SECRET.strip(),
        "APP_PUBLIC_URL": settings.public_url,
        "OIDC_SESSION_SECRET": settings.OIDC_SESSION_SECRET.strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        problems.append(f"OIDC_ENABLED is true but {', '.join(missing)} are not set")
    if settings.public_url and not settings.public_url.lower().startswith(("http://", "https://")):
        problems.append("APP_PUBLIC_URL must be an absolute http(s) URL")
    if settings.oidc_issuer and not settings.oidc_issuer.lower().startswith(
        ("http://", "https://")
    ):
        problems.append("OIDC_ISSUER must be an absolute http(s) URL")
    secret = settings.OIDC_SESSION_SECRET.strip()
    if secret and len(secret) < MIN_SESSION_SECRET_CHARS:
        problems.append(
            f"OIDC_SESSION_SECRET must be at least {MIN_SESSION_SECRET_CHARS} characters "
            "(openssl rand -hex 32)"
        )
    if problems:
        raise RuntimeError("Refusing to start: " + "; ".join(problems))


def validate_production_settings(settings: Settings) -> None:
    """Refuse unsafe configurations in production mode."""
    if settings.APP_ENV != "production":
        return
    problems: list[str] = []
    if "mock" in settings.detector_names:
        problems.append("the mock detector must not be enabled in production (DETECTORS)")
    if settings.APP_ALLOW_INSECURE_CONTENT_LOGGING:
        problems.append("APP_ALLOW_INSECURE_CONTENT_LOGGING must be false in production")
    if "llm" in settings.detector_names and not (settings.OPENAI_API_BASE and settings.LLM_MODEL):
        problems.append("detector 'llm' is enabled but OPENAI_API_BASE/LLM_MODEL are not set")
    if settings.OCR_ENGINE == "llm_vision" and settings.VISION_OCR_PROFILES.strip():
        # Late import: utils.ocr_profiles imports this module.
        from ..utils.ocr_profiles import OcrProfileError, parse_profiles

        try:
            parse_profiles(settings)
        except OcrProfileError as exc:
            problems.append(str(exc))
    if problems:
        raise RuntimeError("Refusing to start: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
