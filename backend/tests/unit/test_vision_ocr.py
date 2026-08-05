import pytest

from backend.src.core.config import Settings
from backend.src.services.vision_llm_ocr import (
    VisionOCRError,
    VisionOCRService,
    _has_text,
    _page_has_ink,
)
from backend.src.utils.extraction import ExtractionError, extract_document
from backend.tests.fake_llm import FakeLLM
from backend.tests.pdf_builder import make_scanned_pdf


def vision_settings(base_url: str = "http://localhost:9", **overrides) -> Settings:
    defaults = dict(
        VISION_OCR_API_BASE=f"{base_url}/v1",
        VISION_OCR_MODEL="baidu/Unlimited-OCR",
        OCR_ENGINE="llm_vision",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_missing_config_fails_with_503():
    with pytest.raises(VisionOCRError) as excinfo:
        VisionOCRService(Settings(OCR_ENGINE="llm_vision"))
    assert excinfo.value.status_code == 503


def test_invalid_extra_body_rejected():
    with pytest.raises(VisionOCRError):
        VisionOCRService(vision_settings(VISION_OCR_EXTRA_BODY="not json"))


async def test_scanned_pdf_transcribed_per_page():
    with FakeLLM([], vision_text="Patient Karla Wagenbrecht, geb. 03.11.1957.") as server:
        settings = vision_settings(server.base_url)
        document = await extract_document(make_scanned_pdf(pages=2), "scan.pdf", settings)

    assert document.source_type == "pdf-ocr"
    assert document.text.count("Karla Wagenbrecht") == 2  # one transcription per page
    assert [p.page_number for p in document.pages] == [1, 2]
    # Page offsets map back into the text.
    first = document.pages[0]
    assert "Karla Wagenbrecht" in document.text[first.start : first.end]
    assert any("OCR" in warning for warning in document.warnings)


async def test_vision_request_carries_unlimited_ocr_recipe():
    extra = '{"skip_special_tokens": false, "vllm_xargs": {"ngram_size": 35, "window_size": 128}}'
    with FakeLLM([], vision_text="Befundtext.") as server:
        settings = vision_settings(server.base_url, VISION_OCR_EXTRA_BODY=extra)
        await extract_document(make_scanned_pdf(pages=1), "scan.pdf", settings)
        request = server.vision_requests()[0]

    assert request["model"] == "baidu/Unlimited-OCR"
    assert request["temperature"] == 0.0
    assert request["max_tokens"] == 8192
    assert request["skip_special_tokens"] is False
    assert request["vllm_xargs"] == {"ngram_size": 35, "window_size": 128}
    parts = request["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "<image>document parsing."}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_unlimited_ocr_layout_prefixes_stripped():
    # Real Unlimited-OCR output format: element type + bounding box per line.
    with FakeLLM(
        [],
        vision_text=(
            "text [112, 76, 681, 95]SYNTHETIC TEST DATA\n"
            "text [114, 117, 548, 135]Patientin: Erika Musterfrau, geb. 03.11.1957\n"
            "title [10, 20, 30, 40]Entlassungsbrief"
        ),
    ) as server:
        settings = vision_settings(server.base_url)
        document = await extract_document(make_scanned_pdf(pages=1), "scan.pdf", settings)
    assert "[112" not in document.text
    assert "Patientin: Erika Musterfrau, geb. 03.11.1957" in document.text
    assert "Entlassungsbrief" in document.text


async def test_special_tokens_stripped_from_transcription():
    with FakeLLM(
        [], vision_text="<|ref|>Befund<|/ref|> Patientin Erika Musterfrau <|det|>[[1,2]]<|/det|>"
    ) as server:
        settings = vision_settings(server.base_url)
        document = await extract_document(make_scanned_pdf(pages=1), "scan.pdf", settings)
    assert "<|" not in document.text
    assert "Erika Musterfrau" in document.text


async def test_unreachable_vision_endpoint_fails_closed():
    settings = vision_settings("http://127.0.0.1:9", VISION_OCR_TIMEOUT_SECONDS=2)
    with pytest.raises(ExtractionError) as excinfo:
        await extract_document(make_scanned_pdf(pages=1), "scan.pdf", settings)
    assert excinfo.value.status_code == 502


async def test_empty_transcriptions_rejected():
    with FakeLLM([], vision_text="") as server:
        settings = vision_settings(server.base_url)
        with pytest.raises(ExtractionError):
            await extract_document(make_scanned_pdf(pages=1), "scan.pdf", settings)


# --- empty-page fallback + fail-closed backstop ------------------------------
#
# Unlimited-OCR's layout parser occasionally classifies a whole page as a
# single "image" region and emits no text (dense barcodes, handwriting,
# redaction bars). Such a page is retried with the flat "Free OCR." prompt; if
# it is STILL empty while the page has ink, the document fails closed rather
# than silently dropping the page and its PII. `image [...]` with empty content
# is exactly what the model returns for a page it declined to transcribe.

_IMAGE_ONLY = "<|det|>image [46, 48, 952, 884]<|/det|>"


def test_page_has_ink_distinguishes_blank_from_content():
    from PIL import Image, ImageDraw

    blank = Image.new("RGB", (200, 200), "white")
    assert _page_has_ink(blank) is False
    inked = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(inked).rectangle((20, 20, 60, 60), fill="black")
    assert _page_has_ink(inked) is True


async def test_empty_inked_page_retried_with_fallback_prompt(monkeypatch):
    service = VisionOCRService(vision_settings())
    monkeypatch.setattr(service, "_render_pages", lambda data: [(b"png", True)])
    prompts: list[str | None] = []

    async def fake_transcribe(page_number, png, prompt=None):
        prompts.append(prompt)
        if prompt is None:  # primary prompt: page misread as one image
            return _IMAGE_ONLY
        return "<|det|>text [10, 10, 90, 20]<|/det|>Patient Karla Wagenbrecht"

    monkeypatch.setattr(service, "_transcribe_page", fake_transcribe)
    pages = await service.process_pdf(b"pdf")

    assert "Karla Wagenbrecht" in "\n".join(line.text for line in pages[0])
    # Primary attempt, then exactly one retry with the fallback prompt.
    assert prompts == [None, service._settings.VISION_OCR_FALLBACK_PROMPT]


async def test_inked_page_blank_under_all_prompts_fails_closed(monkeypatch):
    service = VisionOCRService(vision_settings())
    monkeypatch.setattr(service, "_render_pages", lambda data: [(b"png", True)])

    async def always_image(page_number, png, prompt=None):
        return _IMAGE_ONLY

    monkeypatch.setattr(service, "_transcribe_page", always_image)
    with pytest.raises(VisionOCRError) as excinfo:
        await service.process_pdf(b"pdf")
    assert excinfo.value.status_code == 422
    assert "page 1" in str(excinfo.value)


async def test_blank_page_stays_empty_without_retry(monkeypatch):
    service = VisionOCRService(vision_settings())
    monkeypatch.setattr(service, "_render_pages", lambda data: [(b"png", False)])
    prompts: list[str | None] = []

    async def fake_transcribe(page_number, png, prompt=None):
        prompts.append(prompt)
        return _IMAGE_ONLY

    monkeypatch.setattr(service, "_transcribe_page", fake_transcribe)
    pages = await service.process_pdf(b"pdf")

    assert not _has_text(pages[0])  # genuinely blank page → no text, no error
    assert prompts == [None]  # no fallback retry for a page without ink


async def test_fallback_disabled_fails_closed_without_retry(monkeypatch):
    service = VisionOCRService(vision_settings(VISION_OCR_FALLBACK_PROMPT=""))
    monkeypatch.setattr(service, "_render_pages", lambda data: [(b"png", True)])
    prompts: list[str | None] = []

    async def fake_transcribe(page_number, png, prompt=None):
        prompts.append(prompt)
        return _IMAGE_ONLY

    monkeypatch.setattr(service, "_transcribe_page", fake_transcribe)
    with pytest.raises(VisionOCRError):
        await service.process_pdf(b"pdf")
    assert prompts == [None]  # empty fallback prompt → no retry attempted
