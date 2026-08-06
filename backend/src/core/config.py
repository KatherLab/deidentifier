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
    APP_VERSION: str = "0.1.0"
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

    # Detectors: comma-separated (mock | rules | llm)
    DETECTORS: str = "rules"

    # Primary PII detection LLM (OpenAI-compatible) — Milestone 2
    OPENAI_API_BASE: str = ""
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_REQUEST_TIMEOUT_SECONDS: int = Field(default=120, ge=1)
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
    # Prompt sent with each page image; "<image>document parsing." is the
    # Unlimited-OCR recipe and works for most vision OCR models.
    VISION_OCR_PROMPT: str = "<image>document parsing."
    # Retry prompt for a page that the primary prompt transcribes to (near-)
    # empty text while the rendered page clearly has ink. Unlimited-OCR's
    # layout parser occasionally classifies a whole page as a single image
    # (dense barcodes, handwriting, redaction bars) and emits no text; the flat
    # "Free OCR." mode transcribes it. Empty disables the fallback.
    VISION_OCR_FALLBACK_PROMPT: str = "<image>Free OCR."
    VISION_OCR_MAX_TOKENS: int = Field(default=8192, ge=256)
    # Raw JSON merged into the request body (e.g. Unlimited-OCR's
    # skip_special_tokens / vllm_xargs); empty = none.
    VISION_OCR_EXTRA_BODY: str = ""
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
    if problems:
        raise RuntimeError("Refusing to start: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
