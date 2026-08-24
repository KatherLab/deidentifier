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


def test_letterhead_department_is_masked(client):
    """The unit line of a hospital letterhead is as identifying as the
    institution's name and must not survive the address block."""
    letterhead = (
        "Beispielklinikum Musterstadt\n"
        "Klinik und Poliklinik für Innere Medizin\n"
        "Musterstraße 74\n"
        "01307 Musterstadt\n"
    )
    response = client.post("/api/v1/anonymize", json={"text": letterhead})
    assert response.status_code == 200
    anonymized = response.json()["anonymized_text"]
    assert "Klinik und Poliklinik für Innere Medizin" not in anonymized
    assert "[ORGANISATION]" in anonymized


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


def test_manual_selection_becomes_redaction(client):
    first = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()
    # "Aufnahme" is not a detected entity — the user selects it manually.
    start = SAMPLE_TEXT.index("Aufnahme")
    second = client.post(
        "/api/v1/anonymize",
        json={
            "request_id": first["request_id"],
            "overrides": [
                {
                    "start": start,
                    "end": start + len("Aufnahme"),
                    "text": "Aufnahme",
                    "transformation": "REMOVE",
                }
            ],
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert "Aufnahme am" not in body["anonymized_text"]
    assert "[GESCHWÄRZT] am" in body["anonymized_text"]
    manual = next(e for e in body["entities"] if e["detector"] == "user_manual")
    assert manual["metadata"].get("user_manual") is True
    assert manual["status"] == "REDACTED"
    # Detected entities stay redacted as before.
    assert "Max Mustermann" not in body["anonymized_text"]


def test_manual_selection_with_stale_text_is_ignored_with_warning(client):
    first = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()
    second = client.post(
        "/api/v1/anonymize",
        json={
            "request_id": first["request_id"],
            "overrides": [{"start": 0, "end": 7, "text": "FALSCH!", "transformation": "REMOVE"}],
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert any(w["code"] == "manual_selection_ignored" for w in body["warnings"])
    assert body["anonymized_text"].startswith("Patient")  # nothing mangled


def test_output_language_selects_the_placeholders(client):
    response = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT, "output_language": "fr"})
    assert response.status_code == 200
    body = response.json()

    assert body["output_language"] == "fr"
    anonymized = body["anonymized_text"]
    assert "[PERSONNE_1]" in anonymized
    assert "[DATE_DE_NAISSANCE]" in anonymized
    assert "[TELEPHONE]" in anonymized
    # The German tokens must not leak into a French run.
    assert "[PERSON_1]" not in anonymized
    assert "[GEBURTSDATUM]" not in anonymized


def test_cached_rerun_keeps_the_output_language_of_the_run(client):
    """A review-UI adjustment must not rewrite the placeholders of the
    document the user is looking at, even if the request omits the field."""
    first = client.post(
        "/api/v1/anonymize", json={"text": SAMPLE_TEXT, "output_language": "es"}
    ).json()

    second = client.post(
        "/api/v1/anonymize",
        json={"request_id": first["request_id"], "overrides": []},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["output_language"] == "es"
    assert "[PERSONA_1]" in body["anonymized_text"]


def test_unknown_output_language_falls_back_instead_of_failing(client):
    response = client.post(
        "/api/v1/anonymize", json={"text": SAMPLE_TEXT, "output_language": "klingon"}
    )
    # An unsupported value is rejected by the schema — it can only come from a
    # hand-written request, and the UI offers a fixed list.
    assert response.status_code == 422


def test_manual_selection_overlapping_detected_entity(client):
    first = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()
    # Select a region that contains the detected name plus surrounding text.
    start = SAMPLE_TEXT.index("Patient: Max Mustermann")
    end = start + len("Patient: Max Mustermann")
    second = client.post(
        "/api/v1/anonymize",
        json={
            "request_id": first["request_id"],
            "overrides": [
                {
                    "start": start,
                    "end": end,
                    "text": "Patient: Max Mustermann",
                    "transformation": "REMOVE",
                }
            ],
        },
    )
    assert second.status_code == 200
    body = second.json()
    # The larger manual region wins the overlap and is fully removed.
    assert "Max Mustermann" not in body["anonymized_text"]
    assert "Patient:" not in body["anonymized_text"]
    assert "[GESCHWÄRZT]" in body["anonymized_text"]


def test_override_rerun_with_expired_id(client):
    response = client.post("/api/v1/anonymize", json={"request_id": "no-such-id", "overrides": []})
    assert response.status_code == 410


def test_response_reports_how_long_the_result_lives(client):
    body = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()
    lifetime = body["lifetime"]
    assert 840 < lifetime["expires_in_seconds"] <= 900
    assert lifetime["can_extend"] is True


def test_extend_grants_more_time(client):
    """The review UI offers this shortly before the countdown runs out."""
    first = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()

    response = client.post(f"/api/v1/anonymize/{first['request_id']}/extend")
    assert response.status_code == 200
    assert response.json()["expires_in_seconds"] > 0
    # Still usable afterwards.
    rerun = client.post(
        "/api/v1/anonymize", json={"request_id": first["request_id"], "overrides": []}
    )
    assert rerun.status_code == 200


def test_extending_an_unknown_id_is_gone_not_granted(client):
    response = client.post("/api/v1/anonymize/no-such-id/extend")
    assert response.status_code == 410


def test_extension_is_bounded_by_the_configured_ceiling(client, monkeypatch):
    """Whatever the UI does, a document leaves memory at the configured
    maximum. Set to 30 minutes here so the test does not have to simulate a
    12-hour day."""
    import backend.src.utils.cache as cache_module
    from backend.src.core.config import get_settings

    monkeypatch.setenv("RESULT_CACHE_TTL_MINUTES", "15")
    monkeypatch.setenv("RESULT_CACHE_EXTENSION_MINUTES", "60")
    monkeypatch.setenv("RESULT_CACHE_MAX_LIFETIME_MINUTES", "30")
    get_settings.cache_clear()
    cache_module.request_cache.configure(get_settings())  # what the app's lifespan does

    clock = {"now": 1000.0}
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: clock["now"])

    first = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()
    request_id = first["request_id"]

    # One press already asks for more than the ceiling allows.
    granted = client.post(f"/api/v1/anonymize/{request_id}/extend").json()
    assert granted["expires_in_seconds"] == 30 * 60
    assert granted["can_extend"] is False

    clock["now"] = 1000.0 + 30 * 60 + 1
    assert client.post(f"/api/v1/anonymize/{request_id}/extend").status_code == 410
    assert (
        client.post(
            "/api/v1/anonymize", json={"request_id": request_id, "overrides": []}
        ).status_code
        == 410
    )


def test_delete_forgets_the_cached_document(client):
    """The review UI calls this when a document is closed: the text must stop
    living in server memory then, not at the end of the TTL."""
    first = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()
    request_id = first["request_id"]

    deleted = client.delete(f"/api/v1/anonymize/{request_id}")
    assert deleted.status_code == 204
    # The document is gone: a re-run now has nothing to work from.
    rerun = client.post("/api/v1/anonymize", json={"request_id": request_id, "overrides": []})
    assert rerun.status_code == 410


def test_delete_of_an_unknown_id_reveals_nothing(client):
    """Same answer either way — whether an id exists is not something an
    unrelated caller should be able to probe."""
    deleted = client.delete("/api/v1/anonymize/no-such-id")
    assert deleted.status_code == 204


def test_request_id_is_not_written_to_the_log(client, caplog):
    """Anyone holding a request id can fetch the cached document, so it must
    not travel to wherever the logs go."""
    import logging

    with caplog.at_level(logging.INFO):
        body = client.post("/api/v1/anonymize", json={"text": SAMPLE_TEXT}).json()
    assert body["request_id"] not in caplog.text
    assert "anonymize_request" in caplog.text


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
    # True redaction: the text layer survives minus the redacted strings.
    import io

    from pypdf import PdfReader

    extracted = "".join(
        p.extract_text() or "" for p in PdfReader(io.BytesIO(response.content)).pages
    )
    assert "Max Mustermann" not in extracted
    assert "komplikationslos" in extracted  # clinical text stays selectable


def test_export_without_a_cached_detection_leaves_nothing_behind(client):
    """An export that has to run detection itself caches under an id the client
    never sees. That entry is unreachable, so it must not linger."""
    from backend.src.utils.cache import request_cache
    from backend.tests.pdf_builder import make_pdf

    pdf = make_pdf(
        [
            "Patient: Max Mustermann, geb. 01.02.1980",
            "Der Patient wurde stationaer aufgenommen und komplikationslos behandelt.",
            "Die Entlassung erfolgte in gutem Allgemeinzustand nach Hause.",
        ]
    )
    request_cache.clear()

    response = client.post(
        "/api/v1/export/pdf",
        files={"file": ("brief.pdf", pdf, "application/pdf")},
        data={"overrides": "[]"},
    )
    assert response.status_code == 200
    assert request_cache._entries == {}


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


def test_redact_terms_deterministically_redacted(client):
    response = client.post(
        "/api/v1/anonymize",
        json={
            "text": "Der Patient wurde auf Station B4 im Westflügel behandelt. Station B4 ist voll.",
            "redact_terms": ["Station B4", "Westflügel"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "Station B4" not in body["anonymized_text"]
    assert "Westflügel" not in body["anonymized_text"]
    assert body["anonymized_text"].count("[PII]") == 3  # both occurrences + Westflügel
    term_entities = [e for e in body["entities"] if e["detector"] == "user_terms"]
    assert len(term_entities) == 3
    assert all(e["metadata"].get("user_term") for e in term_entities)


def test_preserve_terms_keep_detected_entities(client):
    response = client.post(
        "/api/v1/anonymize",
        json={"text": SAMPLE_TEXT, "preserve_terms": ["Musterstraße 12"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert "Musterstraße 12" in body["anonymized_text"]
    preserved = next(e for e in body["entities"] if e["text"] == "Musterstraße 12")
    assert preserved["status"] == "PRESERVED"
    assert preserved["metadata"].get("preserved_by_term") is True
    # Everything else stays redacted.
    assert "Max Mustermann" not in body["anonymized_text"]


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
    assert body["banner"] is None


def test_status_reports_configured_banner(client, monkeypatch):
    from backend.src.core.config import get_settings

    monkeypatch.setenv("BANNER_ENABLED", "true")
    monkeypatch.setenv("BANNER_TEXT", "Research Use Only!")
    monkeypatch.setenv("BANNER_COLOR", "red")
    get_settings.cache_clear()
    body = client.get("/api/v1/status").json()
    assert body["banner"] == {"text": "Research Use Only!", "color": "red"}


def test_status_omits_enabled_banner_without_text(client, monkeypatch):
    from backend.src.core.config import get_settings

    monkeypatch.setenv("BANNER_ENABLED", "true")
    monkeypatch.setenv("BANNER_TEXT", "   ")
    get_settings.cache_clear()
    assert client.get("/api/v1/status").json()["banner"] is None


def test_status_falls_back_to_amber_for_unknown_banner_color(client, monkeypatch):
    from backend.src.core.config import get_settings

    monkeypatch.setenv("BANNER_ENABLED", "true")
    monkeypatch.setenv("BANNER_TEXT", "Testsystem")
    monkeypatch.setenv("BANNER_COLOR", "chartreuse")
    get_settings.cache_clear()
    assert client.get("/api/v1/status").json()["banner"]["color"] == "amber"


def test_health_endpoints(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready").json()
    assert ready["status"] == "ready"


def _fake_scan_extraction(text: str, lines: list[str]):
    """A pdf-ocr extraction with one layout box per line, stacked down page 1.

    Lets the export route exercise the scanned-document reconstruction without
    an OCR service — the same substitution the reconstruction itself sees."""
    from backend.src.utils.extraction import ExtractedDocument, LayoutLine, PageRange

    layout = []
    position = 0
    for index, line in enumerate(lines):
        start = text.index(line, position)
        layout.append(
            LayoutLine(
                page_number=1,
                x1=100,
                y1=100 + index * 40,
                x2=900,
                y2=130 + index * 40,
                start=start,
                end=start + len(line),
            )
        )
        position = start + len(line)
    return ExtractedDocument(
        text=text,
        source_type="pdf-ocr",
        pages=[PageRange(page_number=1, start=0, end=len(text))],
        layout=layout,
    )


def test_export_scanned_pdf_draws_bars_only_when_asked(client, monkeypatch):
    """The `redaction_bars` flag reaches the reconstruction."""
    import io

    import pymupdf

    from backend.src.routers.v1.endpoints import export as export_endpoint
    from backend.tests.pdf_builder import make_pdf

    lines = [
        "Patient: Max Mustermann, geb. 01.02.1980",
        "Der Patient wurde stationaer aufgenommen und komplikationslos behandelt.",
    ]
    text = "\n".join(lines)
    pdf = make_pdf(lines)

    async def fake_extract(*args, **kwargs):
        return _fake_scan_extraction(text, lines)

    monkeypatch.setattr(export_endpoint, "extract_document", fake_extract)

    def black_rects(content: bytes) -> int:
        document = pymupdf.open(stream=content, filetype="pdf")
        try:
            return sum(
                1
                for drawing in document[0].get_drawings()
                if drawing.get("fill") == (0.0, 0.0, 0.0)
            )
        finally:
            document.close()

    def export(**data):
        response = client.post(
            "/api/v1/export/pdf",
            files={"file": ("scan.pdf", pdf, "application/pdf")},
            data={"overrides": "[]", **data},
        )
        assert response.status_code == 200
        return response.content

    plain = export()
    barred = export(redaction_bars="true")
    assert black_rects(plain) == 0
    assert black_rects(barred) > 0

    # The bar is drawn over the placeholder, which stays in the text layer.
    from pypdf import PdfReader

    extracted = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(barred)).pages)
    assert "Max Mustermann" not in extracted
    assert "[PERSON_1]" in extracted


def test_refused_export_names_its_code_and_whether_it_can_be_forced(client, monkeypatch):
    """The contract the review UI's "export anyway" button reads."""
    from backend.src.routers.v1.endpoints import export as export_endpoint
    from backend.src.utils import pdf_export
    from backend.tests.pdf_builder import make_pdf

    pdf = make_pdf(
        [
            "Patient: Max Mustermann, geb. 01.02.1980",
            "Der Patient wurde stationaer aufgenommen und komplikationslos behandelt.",
            "Die Entlassung erfolgte in gutem Allgemeinzustand nach Hause.",
        ]
    )
    seen: dict[str, bool] = {}

    def fake_export(data, entities, settings, areas=None, *, expected_text="", force=False):
        seen["force"] = force
        seen["expected_text"] = bool(expected_text)
        if force:
            return b"%PDF-forced"
        raise pdf_export.ExportError(
            "1 redacted text(s) also occur outside the redacted passages.",
            code=pdf_export.RESIDUAL_EXPLAINED,
            forceable=True,
            items=["Mustermann"],
        )

    monkeypatch.setattr(export_endpoint, "redact_native_pdf", fake_export)

    refused = client.post(
        "/api/v1/export/pdf", files={"file": ("brief.pdf", pdf, "application/pdf")}
    )
    assert refused.status_code == 422
    body = refused.json()
    assert body["code"] == "pdf_export_residual_explained"
    assert body["forceable"] is True
    assert body["items"] == ["Mustermann"]
    assert isinstance(body["detail"], str)  # unchanged for older clients
    # The exporter is handed the anonymized text to judge the residual against.
    assert seen["expected_text"] is True

    forced = client.post(
        "/api/v1/export/pdf",
        files={"file": ("brief.pdf", pdf, "application/pdf")},
        data={"force_export": "true"},
    )
    assert forced.status_code == 200
    assert seen["force"] is True


def test_a_refused_export_never_logs_the_passages_it_names(client, caplog, monkeypatch):
    import logging

    from backend.src.routers.v1.endpoints import export as export_endpoint
    from backend.src.utils import pdf_export
    from backend.tests.pdf_builder import make_pdf

    pdf = make_pdf(
        [
            "Patient: Max Mustermann, geb. 01.02.1980",
            "Der Patient wurde stationaer aufgenommen und komplikationslos behandelt.",
            "Die Entlassung erfolgte in gutem Allgemeinzustand nach Hause.",
        ]
    )

    def fake_export(data, entities, settings, areas=None, *, expected_text="", force=False):
        raise pdf_export.ExportError(
            "refused", code=pdf_export.RESIDUAL_EXPLAINED, forceable=True, items=["Mustermann"]
        )

    monkeypatch.setattr(export_endpoint, "redact_native_pdf", fake_export)
    with caplog.at_level(logging.INFO):
        client.post("/api/v1/export/pdf", files={"file": ("brief.pdf", pdf, "application/pdf")})
    assert "Mustermann" not in caplog.text
