"""OCR profile selection through the API: the multipart field switches the
model/dialect, unknown selections fail loudly, and /status advertises what is
selectable."""

import json

from backend.src.core.config import get_settings
from backend.tests.fake_llm import FakeLLM
from backend.tests.pdf_builder import make_scanned_pdf

_CHANDRA_HTML = (
    '<div data-bbox="56 139 253 158" data-label="Text">'
    "<p>SYNTHETIC TEST DATA: Patientin Erika Musterfrau</p></div>"
)


def _configure(monkeypatch, base_url: str) -> None:
    profiles = json.dumps(
        [
            {"name": "Chandra", "model": "chandra-ocr-2", "dialect": "chandra"},
            {"name": "Unlimited", "model": "baidu/Unlimited-OCR", "dialect": "unlimited_ocr"},
        ]
    )
    monkeypatch.setenv("DETECTORS", "rules")
    monkeypatch.setenv("OCR_ENGINE", "llm_vision")
    monkeypatch.setenv("VISION_OCR_API_BASE", f"{base_url}/v1")
    monkeypatch.setenv("VISION_OCR_MODEL", "flat-model")
    monkeypatch.setenv("VISION_OCR_PROFILES", profiles)
    get_settings.cache_clear()


def test_default_profile_is_used_without_selection(client, monkeypatch):
    with FakeLLM([], vision_text=_CHANDRA_HTML) as server:
        _configure(monkeypatch, server.base_url)
        response = client.post(
            "/api/v1/anonymize",
            files={"file": ("scan.pdf", make_scanned_pdf(pages=1), "application/pdf")},
        )
        assert response.status_code == 200
        assert server.vision_requests()[0]["model"] == "chandra-ocr-2"
    assert response.json()["source_type"] == "pdf-ocr"


def test_selected_profile_switches_model_and_dialect(client, monkeypatch):
    unlimited_line = "text [10, 10, 200, 30]SYNTHETIC TEST DATA: Patientin Erika Musterfrau"
    with FakeLLM([], vision_text=unlimited_line) as server:
        _configure(monkeypatch, server.base_url)
        response = client.post(
            "/api/v1/anonymize",
            files={"file": ("scan.pdf", make_scanned_pdf(pages=1), "application/pdf")},
            data={"ocr_profile": "Unlimited"},
        )
        assert response.status_code == 200
        request = server.vision_requests()[0]
    assert request["model"] == "baidu/Unlimited-OCR"
    assert request["vllm_xargs"] == {"ngram_size": 35, "window_size": 128}
    # The unlimited dialect parsed the layout prefix away.
    assert "[10," not in response.json()["source_text"]
    assert "Erika Musterfrau" in response.json()["source_text"]


def test_unknown_profile_is_rejected_before_processing(client, monkeypatch):
    _configure(monkeypatch, "http://localhost:9")
    response = client.post(
        "/api/v1/anonymize",
        files={"file": ("scan.pdf", make_scanned_pdf(pages=1), "application/pdf")},
        data={"ocr_profile": "nope"},
    )
    assert response.status_code == 422
    assert "Chandra" in response.json()["detail"]


def test_stream_rejects_unknown_profile_as_plain_http_error(client, monkeypatch):
    _configure(monkeypatch, "http://localhost:9")
    response = client.post(
        "/api/v1/anonymize/stream",
        files={"file": ("scan.pdf", make_scanned_pdf(pages=1), "application/pdf")},
        data={"ocr_profile": "nope"},
    )
    # Parsed before streaming starts: a regular 422, not an in-stream error.
    assert response.status_code == 422


def test_export_rejects_unknown_profile(client, monkeypatch):
    _configure(monkeypatch, "http://localhost:9")
    response = client.post(
        "/api/v1/export/pdf",
        files={"file": ("scan.pdf", make_scanned_pdf(pages=1), "application/pdf")},
        data={"ocr_profile": "nope"},
    )
    assert response.status_code == 422


def test_status_reports_profiles_and_all_their_endpoints(client, monkeypatch):
    _configure(monkeypatch, "http://localhost:9")
    body = client.get("/api/v1/status").json()
    assert body["ocr_profiles"] == [
        {"name": "Chandra", "model": "chandra-ocr-2", "dialect": "chandra", "default": True},
        {
            "name": "Unlimited",
            "model": "baidu/Unlimited-OCR",
            "dialect": "unlimited_ocr",
            "default": False,
        },
    ]
    assert body["ocr_dialect"] == "chandra"  # the default profile's dialect
    endpoint_names = {e["name"] for e in body["external_endpoints"]}
    assert {"vision_ocr:Chandra", "vision_ocr:Unlimited"} <= endpoint_names


def test_status_without_profiles_is_unchanged(client, monkeypatch):
    monkeypatch.setenv("OCR_ENGINE", "llm_vision")
    monkeypatch.setenv("VISION_OCR_API_BASE", "http://localhost:9/v1")
    monkeypatch.setenv("VISION_OCR_MODEL", "flat-model")
    get_settings.cache_clear()
    body = client.get("/api/v1/status").json()
    assert body["ocr_profiles"] == []
    assert "vision_ocr" in {e["name"] for e in body["external_endpoints"]}


def test_status_surfaces_malformed_profiles(client, monkeypatch):
    monkeypatch.setenv("OCR_ENGINE", "llm_vision")
    monkeypatch.setenv("VISION_OCR_PROFILES", "not json")
    get_settings.cache_clear()
    response = client.get("/api/v1/status")
    assert response.status_code == 500
    assert "VISION_OCR_PROFILES" in response.json()["detail"]
