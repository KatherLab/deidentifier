import io

import pytest

from backend.src.core.config import Settings
from backend.src.schemas.anonymize import RedactArea
from backend.src.schemas.entities import (
    AppliedEntity,
    EntityType,
    SpanStatus,
    TransformationType,
)
from backend.src.utils import pdf_export
from backend.src.utils.extraction import LayoutLine
from backend.src.utils.pdf_export import (
    ExportError,
    _verify_rebuilt,
    anonymize_line,
    rebuild_scanned_pdf,
    redact_native_pdf,
    redacted_texts,
    render_pdf_pages,
)
from backend.tests.pdf_builder import make_pdf


def applied(
    text: str,
    start: int,
    etype: EntityType = EntityType.PERSON_NAME,
    replacement: str | None = "[PERSON_1]",
) -> AppliedEntity:
    status = SpanStatus.PRESERVED if replacement is None else SpanStatus.TAGGED
    return AppliedEntity(
        start=start,
        end=start + len(text),
        text=text,
        entity_type=etype,
        confidence=0.9,
        detector="test",
        transformation=TransformationType.PRESERVE
        if replacement is None
        else TransformationType.CONSISTENT_TAG,
        replacement=replacement,
        status=status,
    )


def entities_for(source: str, fragments: list[tuple[str, str | None]]) -> list[AppliedEntity]:
    result = []
    for fragment, replacement in fragments:
        result.append(applied(fragment, source.index(fragment), replacement=replacement))
    return result


# --- shared helpers ----------------------------------------------------------


def test_redacted_texts_excludes_preserved_and_orders_longest_first():
    source = "Max Mustermann und Max und 10.03.2024"
    entities = entities_for(source, [("Max Mustermann", "[PERSON_1]"), ("Max", "[PERSON_1]")])
    entities.append(applied("10.03.2024", source.index("10.03.2024"), replacement=None))
    texts = redacted_texts(entities)
    assert texts == ["Max Mustermann", "Max"] or texts[0] == "Max Mustermann"
    assert "10.03.2024" not in texts


def test_anonymize_line_replaces_within_line():
    source = "Patientin: Erika Musterfrau, geb. 1957"
    entities = entities_for(source, [("Erika Musterfrau", "[PERSON_1]")])
    line = anonymize_line(source, 0, len(source), entities)
    assert line == "Patientin: [PERSON_1], geb. 1957"


def test_anonymize_line_entity_spanning_lines():
    source = "Herr Max\nMustermann kam"
    entity = applied("Max\nMustermann", 5, replacement="[PERSON_1]")
    first = anonymize_line(source, 0, 8, [entity])  # "Herr Max"
    second = anonymize_line(source, 9, len(source), [entity])  # "Mustermann kam"
    assert first == "Herr [PERSON_1]"
    assert second == " kam"


def test_anonymize_line_preserved_entity_untouched():
    source = "Aufnahme am 10.03.2024 erfolgt"
    entity = applied("10.03.2024", 12, replacement=None)
    assert anonymize_line(source, 0, len(source), [entity]) == source


# --- native path -------------------------------------------------------------


def native_settings() -> Settings:
    return Settings()


def test_native_true_redaction_keeps_text_layer_minus_redacted():
    import pypdfium2 as pdfium

    source_lines = [
        "Patient: Max Mustermann, geb. 01.02.1980",
        "Der Befund war unauffaellig und die Therapie komplikationslos.",
    ]
    pdf = make_pdf(source_lines)
    entities = entities_for("\n".join(source_lines), [("Max Mustermann", "[PERSON_1]")])
    output = redact_native_pdf(pdf, entities, native_settings())

    document = pdfium.PdfDocument(output)
    page = document[0]
    text = page.get_textpage().get_text_range()
    # 1. Clinical text remains selectable; the redacted name is truly gone.
    assert "Befund" in text and "komplikationslos" in text
    assert "Max Mustermann" not in text
    # 2. A visible black redaction bar exists on the rendered page.
    image = page.render(scale=2.0).to_pil().convert("L")
    dark = sum(1 for value in image.getdata() if value < 60)
    assert dark > 500, "expected a visible black redaction bar"
    document.close()


def test_native_true_redaction_scrubs_metadata():
    import pymupdf

    pdf = make_pdf(["Patient: Max Mustermann."])
    entities = entities_for("Patient: Max Mustermann.", [("Max Mustermann", "[PERSON_1]")])
    output = redact_native_pdf(pdf, entities, native_settings())
    document = pymupdf.open(stream=output, filetype="pdf")
    metadata = {k: v for k, v in (document.metadata or {}).items() if v}
    document.close()
    assert not metadata.get("author")
    assert not metadata.get("title")


def test_native_raster_fallback_when_true_redaction_fails(monkeypatch):
    import pypdfium2 as pdfium

    def boom(data, entities, settings):
        raise RuntimeError("simulated pymupdf failure")

    monkeypatch.setattr(pdf_export, "_redact_native_true", boom)
    source = "Patient: Max Mustermann."
    pdf = make_pdf([source])
    entities = entities_for(source, [("Max Mustermann", "[PERSON_1]")])
    output = redact_native_pdf(pdf, entities, native_settings())
    # The fallback output is rasterized: no text layer at all.
    document = pdfium.PdfDocument(output)
    assert document[0].get_textpage().get_text_range().strip() == ""
    document.close()


def test_native_true_redaction_generalized_dob_is_selectable_text():
    import pypdfium2 as pdfium

    source = "Patient geboren am 01.02.1980 in Dresden"
    pdf = make_pdf([source])
    entity = AppliedEntity(
        start=19,
        end=29,
        text="01.02.1980",
        entity_type=EntityType.DATE_OF_BIRTH,
        confidence=0.9,
        detector="test",
        transformation=TransformationType.GENERALIZE,
        replacement="1980",
        status=SpanStatus.GENERALIZED,
    )
    output = redact_native_pdf(pdf, [entity], native_settings())
    document = pdfium.PdfDocument(output)
    text = document[0].get_textpage().get_text_range()
    document.close()
    assert "01.02.1980" not in text
    assert "1980" in text  # the generalized replacement is real, selectable text


def test_native_generalized_dob_shows_year_not_black_bar():
    import pypdfium2 as pdfium

    source_line = "Patient geboren am 01.02.1980 in Dresden"
    pdf = make_pdf([source_line])

    document = pdfium.PdfDocument(pdf)
    page = document[0]
    page_width, page_height = page.get_size()
    textpage = page.get_textpage()
    searcher = textpage.search("01.02.1980", match_case=True)
    index, count = searcher.get_next()
    left, bottom, right, top = textpage.get_charbox(index)
    document.close()

    entity = AppliedEntity(
        start=19,
        end=29,
        text="01.02.1980",
        entity_type=EntityType.DATE_OF_BIRTH,
        confidence=0.9,
        detector="test",
        transformation=TransformationType.GENERALIZE,
        replacement="1980",
        status=SpanStatus.GENERALIZED,
    )
    from backend.src.utils.pdf_export import _redact_native_raster

    output = _redact_native_raster(pdf, [entity], native_settings())

    scale = native_settings().VISION_OCR_RENDER_SCALE
    redacted = pdfium.PdfDocument(output)
    image = redacted[0].render(scale=scale).to_pil().convert("L")
    redacted.close()
    # Crop the region where the date was: must contain white background
    # (erased) AND some dark pixels (the replacement year) — not a black bar.
    crop = image.crop(
        (
            int(left * scale),
            int((page_height - top - 2) * scale),
            int((right + 20) * scale),
            int((page_height - bottom + 2) * scale),
        )
    )
    pixels = list(crop.getdata())
    dark = sum(1 for value in pixels if value < 100)
    light = sum(1 for value in pixels if value > 200)
    assert light > len(pixels) * 0.4, "expected mostly erased (white) region"
    assert 0 < dark < len(pixels) * 0.5, "expected replacement text, not a solid black bar"


def test_native_redaction_fails_closed_when_entity_not_found():
    pdf = make_pdf(["Ganz anderer Inhalt ohne Namen."])
    entities = [applied("Nicht Vorhandener Name", 0)]
    # Offsets are irrelevant for the native path; only the text is searched.
    with pytest.raises(ExportError) as excinfo:
        redact_native_pdf(pdf, entities, native_settings())
    assert "NOT generated" in str(excinfo.value)


def test_native_redaction_name_parts_covered_by_full_name():
    # "Max" (name part) does not appear standalone in the PDF, but inside
    # "Max Mustermann" — that counts as covered, no failure.
    pdf = make_pdf(["Patient: Max Mustermann."])
    source = "Patient: Max Mustermann."
    entities = entities_for(source, [("Max Mustermann", "[PERSON_1]"), ("Max", "[PERSON_1]")])
    output = redact_native_pdf(pdf, entities, native_settings())
    assert output.startswith(b"%PDF")


# --- user-drawn area redaction -----------------------------------------------
#
# make_pdf places its text at x=72pt, first baseline y=720pt (bottom-left
# origin, 16pt line spacing) on a 612x792pt page. In normalized top-left
# coordinates the first line's glyphs span y ≈ 80–95; the box below must stop
# before the second line (y ≈ 100+) or the redaction covers both.


def area_over_first_line() -> RedactArea:
    return RedactArea(page=1, x0=80, y0=72, x1=800, y1=96)


def make_image_pdf() -> tuple[bytes, tuple[float, float, float, float]]:
    """A native PDF with text and one embedded image at a known position.
    Returns (pdf_bytes, image rect in pt, top-left origin)."""
    import pymupdf
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (60, 30), (200, 30, 30)).save(buffer, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 100), "Report text stays.")
    rect = (300.0, 200.0, 420.0, 260.0)
    page.insert_image(pymupdf.Rect(*rect), stream=buffer.getvalue())
    data = document.tobytes()
    document.close()
    return data, rect


def _dark_fraction_in_area(pdf_bytes: bytes, area: RedactArea, scale: float = 2.0) -> float:
    """Fraction of dark pixels inside the area's region of the rendered page."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    page = document[0]
    width, height = page.get_size()
    image = page.render(scale=scale).to_pil().convert("L")
    document.close()
    crop = image.crop(
        (
            int(area.x0 / 1000 * width * scale),
            int(area.y0 / 1000 * height * scale),
            int(area.x1 / 1000 * width * scale),
            int(area.y1 / 1000 * height * scale),
        )
    )
    pixels = list(crop.getdata())
    return sum(1 for value in pixels if value < 60) / max(len(pixels), 1)


def test_native_area_redaction_blacks_out_region_and_removes_text():
    import pypdfium2 as pdfium

    pdf = make_pdf(["Signature Dr. Demo", "Befund unauffaellig."])
    area = area_over_first_line()
    output = redact_native_pdf(pdf, [], native_settings(), areas=[area])

    assert _dark_fraction_in_area(output, area) > 0.8
    # True redaction also removes the text under the box from the text layer.
    document = pdfium.PdfDocument(output)
    text = document[0].get_textpage().get_text_range()
    document.close()
    assert "Signature Dr. Demo" not in text
    assert "unauffaellig" in text


def test_native_area_redaction_erases_embedded_image():
    pdf, (x0, y0, x1, y1) = make_image_pdf()
    area = RedactArea(
        page=1,
        x0=x0 / 612 * 1000 - 5,
        y0=y0 / 792 * 1000 - 5,
        x1=x1 / 612 * 1000 + 5,
        y1=y1 / 792 * 1000 + 5,
    )
    output = redact_native_pdf(pdf, [], native_settings(), areas=[area])
    assert _dark_fraction_in_area(output, area) > 0.8


def test_raster_fallback_applies_area(monkeypatch):
    def boom(data, entities, settings, areas=None):
        raise RuntimeError("simulated pymupdf failure")

    monkeypatch.setattr(pdf_export, "_redact_native_true", boom)
    pdf = make_pdf(["Signature Dr. Demo"])
    area = area_over_first_line()
    output = redact_native_pdf(pdf, [], native_settings(), areas=[area])
    assert (
        _dark_fraction_in_area(output, area, scale=native_settings().VISION_OCR_RENDER_SCALE) > 0.8
    )


def test_area_on_other_page_leaves_page_untouched():
    pdf = make_pdf(["Nothing to hide here."], empty_pages=1)
    area = RedactArea(page=2, x0=100, y0=100, x1=900, y1=900)
    output = redact_native_pdf(pdf, [], native_settings(), areas=[area])
    first_page_area = RedactArea(page=1, x0=100, y0=100, x1=900, y1=900)
    assert _dark_fraction_in_area(output, first_page_area) < 0.05


def test_rebuild_scanned_applies_area():
    source = "Diagnose: unauffaellig"
    layout = [LayoutLine(page_number=1, x1=100, y1=100, x2=800, y2=125, start=0, end=len(source))]
    area = RedactArea(page=1, x0=200, y0=400, x1=600, y1=500)
    output = rebuild_scanned_pdf(source, layout, [], page_count=1, areas=[area])
    assert _dark_fraction_in_area(output, area) > 0.8


def test_redact_area_rejects_empty_rect():
    with pytest.raises(ValueError):
        RedactArea(page=1, x0=500, y0=100, x1=500, y1=200)


# --- page rendering (area editor) --------------------------------------------


def test_render_pdf_pages_returns_images_and_sizes():
    import base64

    pdf = make_pdf(["Hello"], empty_pages=1)
    pages, truncated = render_pdf_pages(pdf)
    assert truncated is False
    assert [entry["page"] for entry in pages] == [1, 2]
    first = pages[0]
    assert (first["width"], first["height"]) == (612.0, 792.0)
    prefix = "data:image/png;base64,"
    assert first["image"].startswith(prefix)
    raw = base64.b64decode(first["image"][len(prefix) :])
    assert raw.startswith(b"\x89PNG")


def test_render_pdf_pages_reports_embedded_image_boxes():
    pdf, (x0, y0, x1, y1) = make_image_pdf()
    pages, _ = render_pdf_pages(pdf)
    boxes = pages[0]["image_boxes"]
    assert len(boxes) == 1
    box = boxes[0]
    assert box["x0"] == pytest.approx(x0 / 612 * 1000, abs=5)
    assert box["y0"] == pytest.approx(y0 / 792 * 1000, abs=5)
    assert box["x1"] == pytest.approx(x1 / 612 * 1000, abs=5)
    assert box["y1"] == pytest.approx(y1 / 792 * 1000, abs=5)


def test_render_pdf_pages_rejects_garbage():
    with pytest.raises(ExportError):
        render_pdf_pages(b"not a pdf")


# --- scanned rebuild ---------------------------------------------------------


def make_layout(source: str, lines: list[str], page: int = 1) -> list[LayoutLine]:
    layout = []
    y = 76
    for line in lines:
        start = source.index(line)
        layout.append(
            LayoutLine(
                page_number=page,
                x1=112,
                y1=y,
                x2=680,
                y2=y + 20,
                start=start,
                end=start + len(line),
            )
        )
        y += 24
    return layout


def test_rebuild_places_anonymized_text_and_verifies():
    from pypdf import PdfReader

    lines = [
        "Patientin: Erika Musterfrau, geb. 03.11.1957",
        "Diagnose: Akute Cholezystitis.",
    ]
    source = "\n".join(lines)
    layout = make_layout(source, lines)
    entities = entities_for(source, [("Erika Musterfrau", "[PERSON_1]")])

    output = rebuild_scanned_pdf(source, layout, entities, page_count=1)
    extracted = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(output)).pages)
    assert "Erika Musterfrau" not in extracted
    assert "[PERSON_1]" in extracted
    assert "Akute Cholezystitis" in extracted
    assert "rekonstruiertes" in extracted  # the reconstruction notice


def test_rebuild_wraps_paragraph_boxes_and_maps_bullets():
    from pypdf import PdfReader

    paragraph = (
        "• Die Patientin wurde nach komplikationslosem Verlauf in gutem "
        "Allgemeinzustand entlassen und eine ambulante Kontrolle wurde "
        "innerhalb von zwei Wochen dringend empfohlen."
    )
    source = paragraph
    # Paragraph-level box: tall (three text lines worth of height).
    layout = [LayoutLine(page_number=1, x1=100, y1=100, x2=900, y2=160, start=0, end=len(source))]
    output = rebuild_scanned_pdf(source, layout, [], page_count=1)
    extracted = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(output)).pages)
    # All words survive (wrapped, not truncated), bullet mapped to "-".
    for word in ("Patientin", "Allgemeinzustand", "empfohlen"):
        assert word in extracted
    assert "•" not in extracted
    assert "- Die Patientin" in extracted.replace("\n", " ")


def test_rebuild_without_layout_fails():
    with pytest.raises(ExportError):
        rebuild_scanned_pdf("Text", [], [], page_count=1)


def test_verify_rebuilt_catches_surviving_pii():
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(100, 700, "Erika Musterfrau")
    pdf.showPage()
    pdf.save()
    entities = [applied("Erika Musterfrau", 0)]
    with pytest.raises(ExportError) as excinfo:
        _verify_rebuilt(buffer.getvalue(), entities)
    assert "Verification failed" in str(excinfo.value)


def test_short_entity_true_redaction_whole_word():
    """An age like '28' must be redacted as a whole word — gone standalone,
    but '2028' elsewhere must remain untouched (and not trip verification)."""
    import re

    import pypdfium2 as pdfium

    source = "Age: 28\nFollow-up in 2028 is planned."
    pdf = make_pdf(["Age: 28", "Follow-up in 2028 is planned."])
    entities = [
        AppliedEntity(
            start=source.index("28"),
            end=source.index("28") + 2,
            text="28",
            entity_type=EntityType.AGE,
            confidence=0.9,
            detector="test",
            transformation=TransformationType.TYPE_MASK,
            replacement="[ALTER]",
            status=SpanStatus.REDACTED,
        )
    ]
    output = redact_native_pdf(pdf, entities, native_settings())
    document = pdfium.PdfDocument(output)
    text = document[0].get_textpage().get_text_range()
    document.close()
    assert not re.search(r"(?<!\w)28(?!\w)", text), "standalone 28 must be gone"
    assert "2028" in text, "embedded occurrences must be preserved"


def test_short_entity_raster_fails_closed_when_only_embedded():
    """If the short needle only exists inside a longer number, word-bounded
    matching must NOT black out the substring — and the export fails closed."""
    from backend.src.utils.pdf_export import _redact_native_raster

    pdf = make_pdf(["Kontrolle im Jahr 2028 geplant."])
    entities = [
        AppliedEntity(
            start=0,
            end=2,
            text="28",
            entity_type=EntityType.AGE,
            confidence=0.9,
            detector="test",
            transformation=TransformationType.TYPE_MASK,
            replacement="[ALTER]",
            status=SpanStatus.REDACTED,
        )
    ]
    with pytest.raises(ExportError):
        _redact_native_raster(pdf, entities, native_settings())


def test_rebuild_verification_tolerates_embedded_short_needles():
    from pypdf import PdfReader  # noqa: F401

    source = "Alter: 28, Kontrolle 2028"
    layout = [LayoutLine(page_number=1, x1=100, y1=100, x2=800, y2=120, start=0, end=len(source))]
    entities = [
        AppliedEntity(
            start=7,
            end=9,
            text="28",
            entity_type=EntityType.AGE,
            confidence=0.9,
            detector="test",
            transformation=TransformationType.TYPE_MASK,
            replacement="[ALTER]",
            status=SpanStatus.REDACTED,
        )
    ]
    # "2028" remains in the rebuilt text; word-bounded verification must pass.
    output = rebuild_scanned_pdf(source, layout, entities, page_count=1)
    assert output.startswith(b"%PDF")


# --- whitespace divergence between extractor and export search ----------------
#
# The detector reads the PDF via docling-serve or pypdf; the export searches it
# via pymupdf / pdfium. Those extractors inject or drop spaces around kerned
# glyphs differently, so an entity string detected as "ABC123XYZ789" can appear
# as "ABC123 XYZ789" in the export's text layer. Locating and verification must
# survive that divergence instead of failing the whole export closed.


def _space_split_pdf() -> tuple[bytes, str]:
    """A PDF whose text layer splits one visual token with an injected space
    (two adjacent text runs with a horizontal gap). Returns (pdf, needle) where
    the needle has NO space but the text layer does."""
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=300, height=120)
    page.insert_text((50, 60), "ABC123")
    page.insert_text((110, 60), "XYZ789")
    data = document.tobytes()
    document.close()
    return data, "ABC123XYZ789"


def test_native_true_locates_needle_split_by_injected_whitespace():
    import pymupdf

    pdf, needle = _space_split_pdf()
    # search_for cannot find it (the text layer has a space the needle lacks).
    source = pymupdf.open(stream=pdf, filetype="pdf")
    hits = source[0].search_for(needle)
    source.close()
    assert hits == []

    output = redact_native_pdf(pdf, [applied(needle, 0)], native_settings())
    document = pymupdf.open(stream=output, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    document.close()
    # Redacted in both the literal and whitespace-stripped forms.
    assert "ABC123" not in text and "XYZ789" not in text


def test_native_raster_locates_needle_split_by_injected_whitespace():
    import pypdfium2 as pdfium

    from backend.src.utils.pdf_export import _redact_native_raster

    pdf, needle = _space_split_pdf()
    output = _redact_native_raster(pdf, [applied(needle, 0)], native_settings())

    document = pdfium.PdfDocument(output)
    image = document[0].render(scale=2.0).to_pil().convert("L")
    document.close()
    dark = sum(1 for value in image.getdata() if value < 60)
    assert dark > 300, "expected a visible black redaction bar over the split token"


def test_verify_native_catches_needle_surviving_with_injected_whitespace():
    from backend.src.utils.pdf_export import _verify_native

    pdf, needle = _space_split_pdf()
    # The needle survives in the (unredacted) text layer as "ABC123 XYZ789";
    # verification must catch it despite the injected space (fail-closed).
    with pytest.raises(ExportError):
        _verify_native(pdf, [needle])


# True redaction searches each page for the redacted STRING, so it cannot honour
# a per-occurrence decision: keeping one "Müller" while the others are redacted
# blacks out all of them. The text export, applied by offset, keeps it. These
# pin the predicate that lets the UI warn about that divergence.
def test_preserved_duplicate_is_reported_at_risk():
    entities = [
        applied("Mueller", 0),
        applied("Mueller", 40, replacement=None),
    ]
    assert pdf_export.preserved_texts_at_risk(entities) == ["Mueller"]


def test_preserved_text_nobody_redacts_is_not_at_risk():
    entities = [
        applied("Mueller", 0),
        applied("Schmidt", 40, replacement=None),
    ]
    assert pdf_export.preserved_texts_at_risk(entities) == []


def test_a_preserved_passage_containing_a_redacted_one_is_at_risk():
    # search_for is substring-wise: blacking out "Mueller" also hits the
    # "Mueller" inside a longer passage the reviewer kept.
    entities = [
        applied("Mueller", 0),
        applied("Mueller-Luedenscheidt", 40, replacement=None),
    ]
    assert pdf_export.preserved_texts_at_risk(entities) == ["Mueller-Luedenscheidt"]


def test_nothing_is_at_risk_when_nothing_is_redacted():
    assert pdf_export.preserved_texts_at_risk([applied("Mueller", 0, replacement=None)]) == []


def test_true_redaction_really_does_black_out_the_preserved_duplicate():
    """The behaviour the warning exists for — asserted, not assumed."""
    text = "Befund von Mueller.\nZweitmeinung von Mueller.\n"
    first = text.index("Mueller")
    second = text.index("Mueller", first + 1)
    entities = [
        applied("Mueller", first),
        applied("Mueller", second, replacement=None),
    ]
    output = redact_native_pdf(make_pdf(text), entities, Settings())

    import pymupdf

    document = pymupdf.open(stream=output, filetype="pdf")
    extracted = "".join(page.get_text() for page in document)
    # Both are gone, including the one the reviewer chose to keep.
    assert "Mueller" not in extracted.replace("\n", "")
    assert pdf_export.preserved_texts_at_risk(entities) == ["Mueller"]
