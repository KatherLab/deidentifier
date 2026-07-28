import pytest

from backend.src.core.config import Settings
from backend.src.services.vision_llm_ocr import VisionOCRError, VisionOCRService
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
