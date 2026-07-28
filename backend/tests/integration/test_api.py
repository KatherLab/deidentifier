from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "files"

SAMPLE_TEXT = (
    "Patient: Max Mustermann, geb. 01.02.1980\n"
    "Anschrift: Musterstraße 12, 01307 Dresden\n"
    "Pat.-Nr.: PAT-123456\n"
    "Aufnahme am 10.03.2024. Rückfragen: Tel.: 0351 458-0,\n"
    "E-Mail: chirurgie@beispiel-klinikum.de\n"
)


def test_anonymize_text(client):
    response = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT})
    assert response.status_code == 200
    body = response.json()

    anonymized = body["anonymized_text"]
    assert "Max Mustermann" not in anonymized
    assert "[PERSON_1]" in anonymized
    assert "geb. [GEBURTSDATUM]" in anonymized  # DOB masked by default
    assert "01.02.1980" not in anonymized
    assert "[ADRESSE]" in anonymized
    assert "[TELEFON]" in anonymized
    assert "[E-MAIL]" in anonymized
    assert "[ID]" in anonymized
    assert "10.03.2024" in anonymized  # clinical dates preserved by default

    assert body["source_text"] == SAMPLE_TEXT
    assert body["source_type"] == "paste"
    assert body["entities"]
    for entity in body["entities"]:
        chars = SAMPLE_TEXT[entity["start"] : entity["end"]]
        assert chars == entity["text"]
    assert body["validation"]["status"] in {"PASS", "REVIEW_REQUIRED"}
    assert body["timing_ms"]["total"] >= 0


def test_anonymize_txt_upload(client):
    fixture = FIXTURES / "synthetic_discharge.txt"
    with fixture.open("rb") as fh:
        response = client.post(
            "/api/v1/anonymize", files={"file": ("synthetic_discharge.txt", fh, "text/plain")}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "txt"
    assert "Max Mustermann" not in body["anonymized_text"]
    assert "Erika Musterfrau" not in body["anonymized_text"]


def test_no_store_headers_on_api_routes(client):
    response = client.post("/api/v1/anonymize", json={"text": "Kein PII hier."})
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_pdf_upload_extracted_and_anonymized(client):
    from backend.tests.pdf_builder import make_pdf

    pdf = make_pdf(
        [
            "Patient: Max Mustermann, geb. 01.02.1980",
            "Pat.-Nr.: PAT-123456",
            "Der Patient wurde stationaer aufgenommen und komplikationslos behandelt.",
            "Die Entlassung erfolgte in gutem Allgemeinzustand nach Hause.",
        ]
    )
    response = client.post(
        "/api/v1/anonymize", files={"file": ("brief.pdf", pdf, "application/pdf")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "pdf"
    assert "Max Mustermann" not in body["anonymized_text"]
    assert "[ID]" in body["anonymized_text"]


def test_scanned_pdf_rejected_with_clear_message(client):
    from backend.tests.pdf_builder import make_scanned_pdf

    response = client.post(
        "/api/v1/anonymize",
        files={"file": ("scan.pdf", make_scanned_pdf(), "application/pdf")},
    )
    assert response.status_code == 422
    assert "scanned" in response.json()["detail"]


def test_docx_upload_extracted_and_anonymized(client):
    from backend.tests.unit.test_extraction import make_docx

    response = client.post(
        "/api/v1/anonymize",
        files={
            "file": (
                "brief.docx",
                make_docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "docx"
    assert "Max Mustermann" not in body["anonymized_text"]


def test_override_rerun_preserves_entity(client):
    first = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()
    address = next(
        e
        for e in first["entities"]
        if e["text"] == "Musterstraße 12" and e["status"] != "PRESERVED"
    )
    second = client.post(
        "/api/v1/anonymize",
        json={
            "request_id": first["request_id"],
            "overrides": [
                {
                    "start": address["start"],
                    "end": address["end"],
                    "text": address["text"],
                    "transformation": "PRESERVE",
                }
            ],
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert body["request_id"] == first["request_id"]
    assert "Musterstraße 12" in body["anonymized_text"]
    overridden = next(e for e in body["entities"] if e["text"] == "Musterstraße 12")
    assert overridden["status"] == "PRESERVED"
    # Everything else stays redacted.
    assert "Max Mustermann" not in body["anonymized_text"]


def test_override_rerun_with_expired_id(client):
    response = client.post("/api/v1/anonymize", json={"request_id": "no-such-id", "overrides": []})
    assert response.status_code == 410


def test_export_pdf_native_with_cached_detection(client):
    from backend.tests.pdf_builder import make_pdf

    pdf = make_pdf(
        [
            "Patient: Max Mustermann, geb. 01.02.1980",
            "Der Patient wurde stationaer aufgenommen und komplikationslos behandelt.",
            "Die Entlassung erfolgte in gutem Allgemeinzustand nach Hause.",
        ]
    )
    first = client.post(
        "/api/v1/anonymize", files={"file": ("brief.pdf", pdf, "application/pdf")}
    ).json()
    response = client.post(
        "/api/v1/export/pdf",
        files={"file": ("brief.pdf", pdf, "application/pdf")},
        data={"request_id": first["request_id"], "overrides": "[]"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "anonymisiert.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
    # Rasterized output: no text layer to leak.
    import io

    from pypdf import PdfReader

    extracted = "".join(
        p.extract_text() or "" for p in PdfReader(io.BytesIO(response.content)).pages
    )
    assert extracted.strip() == ""


def test_custom_policy_overlays_defaults(client):
    response = client.post(
        "/api/v1/anonymize",
        json={
            "text": SAMPLE_TEXT,
            "policy": {"DATE_OF_BIRTH": "GENERALIZE", "ADDRESS": "PRESERVE"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "geb. 1980" in body["anonymized_text"]  # GENERALIZE instead of mask
    assert "Musterstraße 12" in body["anonymized_text"]  # ADDRESS preserved
    assert "Max Mustermann" not in body["anonymized_text"]  # defaults intact


def test_custom_policy_carries_into_override_rerun(client):
    first = client.post(
        "/api/v1/anonymize",
        json={"text": SAMPLE_TEXT, "policy": {"DATE_OF_BIRTH": "GENERALIZE"}},
    ).json()
    second = client.post(
        "/api/v1/anonymize",
        json={
            "request_id": first["request_id"],
            "overrides": [],
            "policy": {"DATE_OF_BIRTH": "GENERALIZE"},
        },
    )
    assert second.status_code == 200
    assert "geb. 1980" in second.json()["anonymized_text"]


def test_invalid_policy_rejected(client):
    response = client.post(
        "/api/v1/anonymize",
        json={"text": "Ein Text.", "policy": {"NO_SUCH_TYPE": "TYPE_MASK"}},
    )
    assert response.status_code == 422


def test_export_pdf_rejects_non_pdf(client):
    response = client.post(
        "/api/v1/export/pdf", files={"file": ("brief.txt", b"text", "text/plain")}
    )
    assert response.status_code == 415


def test_llm_detector_unconfigured_fails_closed(client, monkeypatch):
    from backend.src.core.config import get_settings

    monkeypatch.setenv("DETECTORS", "rules,llm")
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    get_settings.cache_clear()
    response = client.post("/api/v1/anonymize", json={"text": "Ein Text."})
    assert response.status_code == 503
    assert "NOT anonymized" in response.json()["detail"]


def test_unknown_extension_rejected(client):
    response = client.post(
        "/api/v1/anonymize", files={"file": ("data.xlsx", b"PK", "application/octet-stream")}
    )
    assert response.status_code == 415


def test_binary_content_rejected(client):
    response = client.post(
        "/api/v1/anonymize", files={"file": ("data.txt", b"\x00\x01\x02", "text/plain")}
    )
    assert response.status_code == 415


def test_oversized_text_rejected(client, monkeypatch):
    from backend.src.core.config import get_settings

    monkeypatch.setenv("APP_MAX_TEXT_CHARS", "50")
    get_settings.cache_clear()
    response = client.post("/api/v1/anonymize", json={"text": "x" * 100})
    assert response.status_code == 413


def test_empty_text_rejected(client):
    response = client.post("/api/v1/anonymize", json={"text": "   "})
    assert response.status_code == 422


def test_missing_text_field_rejected_without_echo(client):
    response = client.post("/api/v1/anonymize", json={"nope": "value"})
    assert response.status_code == 422
    assert "value" not in response.text


def test_status_endpoint(client):
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["app_env"]
    names = {d["name"] for d in body["detectors"]}
    assert {"mock", "rules"} <= names
    assert all(d["ready"] for d in body["detectors"])
    assert body["limits"]["max_upload_mb"] > 0


def test_health_endpoints(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready").json()
    assert ready["status"] == "ready"
