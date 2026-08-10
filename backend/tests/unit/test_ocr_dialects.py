"""Vision-OCR dialects: response parsing per model family, request recipes,
and the explicit-setting-beats-dialect-default precedence."""

import pytest

from backend.src.core.config import Settings
from backend.src.services.ocr_dialects import (
    ChandraDialect,
    PlainDialect,
    UnlimitedOcrDialect,
    build_dialect,
)
from backend.src.services.vision_llm_ocr import VisionOCRError, VisionOCRService
from backend.src.utils.extraction import extract_document
from backend.tests.fake_llm import FakeLLM
from backend.tests.pdf_builder import make_scanned_pdf


def vision_settings(base_url: str = "http://localhost:9", **overrides) -> Settings:
    defaults = dict(
        VISION_OCR_API_BASE=f"{base_url}/v1",
        VISION_OCR_MODEL="test-ocr",
        OCR_ENGINE="llm_vision",
    )
    defaults.update(overrides)
    return Settings(**defaults)


# SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION. The exact block/label
# shapes chandra-ocr-2 emits: labelled divs with 0–1000-normalized bboxes.
_CHANDRA_HTML = (
    '<div data-bbox="321 53 628 78" data-label="Page-Header">'
    "<p>SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION</p></div>\n"
    '<div data-bbox="56 139 253 158" data-label="Text">'
    "<p>Patientin: Erika Musterfrau<br/>geb. 03.11.1957</p></div>\n"
    '<div data-bbox="66 388 333 401" data-label="Section-Header"><p>DIAGNOSE</p></div>\n'
    '<div data-bbox="54 413 861 533" data-label="List-Group">'
    "<ul><li>Befund A &amp; B</li><li>Befund C</li></ul></div>\n"
    '<div data-bbox="131 133 253 158" data-label="Image">'
    '<img alt="Redacted patient name"/></div>\n'
    '<div data-bbox="602 865 890 955" data-label="Table">\n<table border="1">\n'
    "<tr><td>Kriterium</td><td>Ja</td></tr>\n"
    '<tr><td colspan="2">Datum: 01.02.2024</td></tr>\n</table>\n</div>'
)


# --- registry ----------------------------------------------------------------


def test_registry_builds_every_dialect():
    for name in ("unlimited_ocr", "chandra", "plain"):
        assert build_dialect(name).name == name


def test_unknown_dialect_is_refused_loudly():
    with pytest.raises(ValueError, match="chandra"):
        build_dialect("does_not_exist")


def test_service_rejects_unknown_dialect_with_503():
    with pytest.raises(VisionOCRError) as excinfo:
        VisionOCRService(vision_settings(VISION_OCR_DIALECT="does_not_exist"))
    assert excinfo.value.status_code == 503


# --- parsing: unlimited_ocr --------------------------------------------------


def test_unlimited_parse_strips_layout_prefixes_and_special_tokens():
    lines = UnlimitedOcrDialect().parse(
        "<|ref|>x<|/ref|>text [112, 76, 681, 95]Patientin: Erika Musterfrau\nfreier Text"
    )
    assert [line.text for line in lines] == ["Patientin: Erika Musterfrau", "freier Text"]
    assert lines[0].box == (112, 76, 681, 95)
    assert lines[1].box is None


# --- parsing: chandra --------------------------------------------------------


def test_chandra_parse_blocks_lines_and_boxes():
    lines = ChandraDialect().parse(_CHANDRA_HTML)
    assert [line.text for line in lines] == [
        "SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION",
        "Patientin: Erika Musterfrau",
        "geb. 03.11.1957",
        "DIAGNOSE",
        "- Befund A & B",
        "- Befund C",
        "[Redacted patient name]",
        "Kriterium | Ja",
        "Datum: 01.02.2024",
    ]
    # A multi-line block's box is subdivided into equal vertical strips, so
    # the reconstructed PDF does not overprint the block's lines onto each
    # other. Block "Text" is (56, 139, 253, 158); block "Table" is
    # (602, 865, 890, 955).
    assert lines[1].box == (56, 139, 253, 149)
    assert lines[2].box == (56, 149, 253, 158)
    assert lines[7].box == (602, 865, 890, 910)
    assert lines[8].box == (602, 910, 890, 955)
    # A single-line block keeps the full block box.
    assert lines[6].box == (131, 133, 253, 158)


def test_chandra_parse_ordered_lists_and_clamped_boxes():
    lines = ChandraDialect().parse(
        '<div data-bbox="-5 0 1200 400" data-label="List-Group">'
        "<ol><li>erstens</li><li>zweitens</li></ol></div>"
    )
    assert [line.text for line in lines] == ["1. erstens", "2. zweitens"]
    # Clamped to 0–1000, then subdivided into two strips.
    assert lines[0].box == (0, 0, 1000, 200)
    assert lines[1].box == (0, 200, 1000, 400)


def test_chandra_parse_accepts_plain_text_fallback_output():
    # The fallback prompt asks for plain text; the parser must not drop it.
    lines = ChandraDialect().parse("Zeile eins\nZeile zwei")
    assert [line.text for line in lines] == ["Zeile eins", "Zeile zwei"]
    assert all(line.box is None for line in lines)


def test_chandra_parse_unwraps_code_fences():
    fenced = "```html\n" + '<div data-label="Text"><p>Befund</p></div>' + "\n```"
    assert [line.text for line in ChandraDialect().parse(fenced)] == ["Befund"]


# --- parsing: plain ----------------------------------------------------------


def test_plain_parse_keeps_lines_verbatim_without_boxes():
    lines = PlainDialect().parse("# Befund\n\nPatientin: Erika Musterfrau")
    assert [line.text for line in lines] == ["# Befund", "Patientin: Erika Musterfrau"]
    assert all(line.box is None for line in lines)


# --- request recipes ---------------------------------------------------------


async def test_unlimited_dialect_default_recipe():
    with FakeLLM([], vision_text="Befundtext.") as server:
        settings = vision_settings(server.base_url)
        await extract_document(make_scanned_pdf(pages=1), "scan.pdf", settings)
        request = server.vision_requests()[0]

    assert request["max_tokens"] == 8192
    assert "top_p" not in request
    assert request["skip_special_tokens"] is False
    assert request["vllm_xargs"] == {"ngram_size": 35, "window_size": 128}
    parts = request["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "<image>document parsing."}


async def test_chandra_dialect_recipe_and_extraction():
    with FakeLLM([], vision_text=_CHANDRA_HTML) as server:
        settings = vision_settings(server.base_url, VISION_OCR_DIALECT="chandra")
        document = await extract_document(make_scanned_pdf(pages=1), "scan.pdf", settings)
        request = server.vision_requests()[0]

    assert request["max_tokens"] == 12384
    assert request["top_p"] == 0.1
    assert "vllm_xargs" not in request and "skip_special_tokens" not in request
    parts = request["messages"][0]["content"]
    assert parts[0]["type"] == "image_url"  # chandra wants the image first
    assert parts[1] == {"type": "text", "text": ChandraDialect.default_prompt}

    assert document.source_type == "pdf-ocr"
    assert "Patientin: Erika Musterfrau" in document.text
    # Block boxes feed the layout-preserving PDF reconstruction.
    boxed = [line for line in document.layout if line.page_number == 1]
    assert boxed and all(0 <= line.x1 <= line.x2 <= 1000 for line in boxed)
    span = next(
        line
        for line in boxed
        if document.text[line.start : line.end] == "Patientin: Erika Musterfrau"
    )
    # First strip of the two-line "Text" block (56, 139, 253, 158).
    assert (span.x1, span.y1, span.x2, span.y2) == (56, 139, 253, 149)


async def test_explicit_settings_override_dialect_defaults():
    with FakeLLM([], vision_text=_CHANDRA_HTML) as server:
        settings = vision_settings(
            server.base_url,
            VISION_OCR_DIALECT="chandra",
            VISION_OCR_PROMPT="custom prompt",
            VISION_OCR_MAX_TOKENS=512,
            VISION_OCR_EXTRA_BODY='{"custom": true}',
        )
        await extract_document(make_scanned_pdf(pages=1), "scan.pdf", settings)
        request = server.vision_requests()[0]

    assert request["max_tokens"] == 512
    assert request["custom"] is True
    parts = request["messages"][0]["content"]
    assert parts[1] == {"type": "text", "text": "custom prompt"}
