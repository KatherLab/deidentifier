"""The redacted PDF cannot honour a per-occurrence "keep".

True redaction locates text by searching each page for the redacted string, so
keeping ONE of several identical passages still leaves every one of them black
in the PDF — while the text export, applied by offset, shows the kept one. The
pipeline says so instead of letting the two exports disagree in silence.
"""

from backend.src.core.config import Settings
from backend.src.schemas.anonymize import EntityOverride
from backend.src.utils.notices import PDF_PRESERVE_NOT_HONOURED
from backend.src.utils.pipeline import run_anonymization

TEXT = "Befund von Anna Mueller.\nZweitmeinung von Anna Mueller.\n"
FIRST = TEXT.index("Anna Mueller")
SECOND = TEXT.index("Anna Mueller", FIRST + 1)


def settings() -> Settings:
    return Settings(DETECTORS="mock", LLM_RECHECK_ENABLED=False)


def keep(start: int) -> EntityOverride:
    return EntityOverride(
        start=start, end=start + len("Anna Mueller"), text="Anna Mueller", transformation="PRESERVE"
    )


def codes(response) -> list[str]:
    return [warning.code for warning in response.warnings]


async def _run(source_type: str, overrides: list[EntityOverride] | None = None):
    return await run_anonymization(
        TEXT,
        settings(),
        source_type=source_type,
        overrides=overrides,
        redact_terms=["Anna Mueller"],
    )


async def test_warns_when_one_of_several_identical_passages_is_kept():
    response = await _run("pdf", [keep(SECOND)])
    assert PDF_PRESERVE_NOT_HONOURED in codes(response)
    # The text output does keep it — that is exactly the divergence.
    assert "Anna Mueller" in response.anonymized_text


async def test_silent_when_every_occurrence_is_kept():
    # Keeping ALL of them is the way out, and the multi-selection in the review
    # UI is what makes it one action. Nothing is left to search for.
    response = await _run("pdf", [keep(FIRST), keep(SECOND)])
    assert PDF_PRESERVE_NOT_HONOURED not in codes(response)


async def test_silent_when_nothing_was_kept():
    response = await _run("pdf")
    assert PDF_PRESERVE_NOT_HONOURED not in codes(response)


async def test_silent_for_a_text_source():
    # No PDF to export; the text output honours the decision exactly.
    response = await _run("paste", [keep(SECOND)])
    assert PDF_PRESERVE_NOT_HONOURED not in codes(response)


async def test_silent_for_a_scanned_pdf():
    # The scanned reconstruction rebuilds each line by offset (anonymize_line),
    # so a single kept occurrence comes through correctly there.
    response = await _run("pdf-ocr", [keep(SECOND)])
    assert PDF_PRESERVE_NOT_HONOURED not in codes(response)
