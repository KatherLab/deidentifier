import io

import pytest

from backend.src.core.config import Settings
from backend.src.schemas.entities import (
    AppliedEntity,
    EntityType,
    SpanStatus,
    TransformationType,
)
from backend.src.utils.extraction import LayoutLine
from backend.src.utils.pdf_export import (
    ExportError,
    _verify_rebuilt,
    anonymize_line,
    rebuild_scanned_pdf,
    redact_native_pdf,
    redacted_texts,
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


def test_native_redaction_produces_textless_pdf_with_black_boxes():
    import pypdfium2 as pdfium

    source_lines = [
        "Patient: Max Mustermann, geb. 01.02.1980",
        "Der Befund war unauffaellig und die Therapie komplikationslos.",
    ]
    pdf = make_pdf(source_lines)

    # Locate the name's box in the original for the pixel check.
    document = pdfium.PdfDocument(pdf)
    page = document[0]
    page_width, page_height = page.get_size()
    textpage = page.get_textpage()
    searcher = textpage.search("Max Mustermann", match_case=True)
    index, count = searcher.get_next()
    left, bottom, right, top = textpage.get_charbox(index)
    document.close()

    entities = entities_for("\n".join(source_lines), [("Max Mustermann", "[PERSON_1]")])
    output = redact_native_pdf(pdf, entities, native_settings())

    # 1. The output has no text layer at all (rasterized).
    redacted = pdfium.PdfDocument(output)
    assert len(redacted) == 1
    out_textpage = redacted[0].get_textpage()
    assert out_textpage.get_text_range().strip() == ""

    # 2. The pixels where the name was are black.
    scale = native_settings().VISION_OCR_RENDER_SCALE
    image = redacted[0].render(scale=scale).to_pil().convert("RGB")
    x = int((left + 5) * scale)
    y = int((page_height - top + 3) * scale)
    pixel = image.getpixel((x, y))
    assert sum(pixel) < 90, f"expected black-ish pixel, got {pixel}"
    redacted.close()


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
