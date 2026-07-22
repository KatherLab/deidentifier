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

_env_path = Path(os.getenv("ENV_PATH", "backend/.env"))
_env_file = str(_env_path) if _env_path.is_file() else None


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

    # Detectors: comma-separated (mock | rules | llm | privacy_filter)
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

    # Optional second-net detector — Milestone 3
    PRIVACY_FILTER_ENABLED: bool = False
    PRIVACY_FILTER_BASE_URL: str = ""

    @property
    def detector_names(self) -> list[str]:
        return [d.strip() for d in self.DETECTORS.split(",") if d.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.APP_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.APP_MAX_UPLOAD_MB * 1024 * 1024


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
