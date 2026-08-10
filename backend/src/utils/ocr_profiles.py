"""Named vision-OCR profiles: several models configured at once, one selectable
per document.

`VISION_OCR_PROFILES` (raw JSON list in .env) declares the selectable
configurations; each entry names a model + dialect and may override the
endpoint or recipe values. Everything an entry leaves out is inherited from
the flat `VISION_OCR_*` settings, which double as the inheritance base — so
two models behind one endpoint are just `{"name", "model", "dialect"}`
entries. The first entry is the default. When the variable is unset, the flat
settings are the one and only configuration and nothing changes.

Resolution happens at the endpoint boundary: `resolve_vision_ocr_profile()`
returns an effective `Settings` copy, so the pipeline below never knows
profiles exist. A selected profile that is not configured is refused with 422
— never silently swapped for the default (principle 5): the reviewer chose
where the document goes.
"""

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.config import Settings
from ..services.ocr_dialects import DIALECTS


class OcrProfileError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class OcrProfile(BaseModel):
    """One selectable vision-OCR configuration. Unset fields inherit the flat
    VISION_OCR_* settings. `extra="forbid"`: a typo'd key must fail loudly,
    not configure nothing."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1)
    dialect: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    prompt: str | None = None
    fallback_prompt: str | None = None
    max_tokens: int | None = Field(default=None, ge=256)
    extra_body: dict | None = None


def parse_profiles(settings: Settings) -> list[OcrProfile]:
    """Parse VISION_OCR_PROFILES; empty/unset means the feature is off."""
    raw = (settings.VISION_OCR_PROFILES or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OcrProfileError("VISION_OCR_PROFILES is not valid JSON.") from exc
    if not isinstance(payload, list):
        raise OcrProfileError("VISION_OCR_PROFILES must be a JSON list of profile objects.")
    try:
        profiles = [OcrProfile.model_validate(entry) for entry in payload]
    except ValidationError as exc:
        raise OcrProfileError(
            f"VISION_OCR_PROFILES is invalid: {exc.error_count()} error(s); "
            "each entry needs 'name' and 'model'."
        ) from exc
    names = [profile.name for profile in profiles]
    if len(set(names)) != len(names):
        raise OcrProfileError("VISION_OCR_PROFILES contains duplicate profile names.")
    for profile in profiles:
        if profile.dialect is not None and profile.dialect not in DIALECTS:
            known = ", ".join(sorted(DIALECTS))
            raise OcrProfileError(
                f"OCR profile '{profile.name}' names unknown dialect "
                f"'{profile.dialect}'; known: {known}."
            )
    return profiles


def resolve_vision_ocr_profile(settings: Settings, name: str | None) -> Settings:
    """Return the effective Settings for the selected (or default) profile.

    No profiles configured + no selection -> the flat settings, unchanged.
    Unknown selection -> 422; the choice is the reviewer's, never guessed.
    """
    profiles = parse_profiles(settings)
    if not profiles:
        if name:
            raise OcrProfileError(
                f"OCR profile '{name}' was requested, but no profiles are "
                "configured (VISION_OCR_PROFILES).",
                status_code=422,
            )
        return settings
    if name:
        profile = next((p for p in profiles if p.name == name), None)
        if profile is None:
            known = ", ".join(p.name for p in profiles)
            raise OcrProfileError(
                f"Unknown OCR profile '{name}'; configured: {known}.", status_code=422
            )
    else:
        profile = profiles[0]

    update: dict = {"VISION_OCR_MODEL": profile.model}
    if profile.dialect is not None:
        update["VISION_OCR_DIALECT"] = profile.dialect
    if profile.api_base is not None:
        update["VISION_OCR_API_BASE"] = profile.api_base
    if profile.api_key is not None:
        update["VISION_OCR_API_KEY"] = profile.api_key
    if profile.prompt is not None:
        update["VISION_OCR_PROMPT"] = profile.prompt
    if profile.fallback_prompt is not None:
        update["VISION_OCR_FALLBACK_PROMPT"] = profile.fallback_prompt
    if profile.max_tokens is not None:
        update["VISION_OCR_MAX_TOKENS"] = profile.max_tokens
    if profile.extra_body is not None:
        update["VISION_OCR_EXTRA_BODY"] = json.dumps(profile.extra_body)
    return settings.model_copy(update=update)
