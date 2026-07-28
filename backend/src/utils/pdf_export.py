"""Redacted-PDF export.

Two paths, chosen automatically — the user never picks between a safe and an
unsafe option:

Native PDFs → rasterize + exact blackout. pdfium's text layer provides
per-character boxes for the same text the detectors saw; every occurrence of
every redacted entity string is covered with black rectangles on the rendered
page images, and the output is a fresh image-based PDF. It physically cannot
contain a hidden text layer, original metadata, or embedded objects. If any
redacted string cannot be located on any page, the export FAILS (never emit a
possibly incomplete redaction).

Scanned PDFs → layout-faithful rebuild. The original pixels are discarded
entirely (fail-closed); the anonymized text is re-typeset at the OCR bounding
boxes (0–1000 normalized). The result is re-extracted and checked: no
redacted entity string may survive in the output.
"""

import io
import re

from ..core.config import Settings
from ..schemas.entities import AppliedEntity, SpanStatus
from .extraction import LayoutLine

_PAGE_A4 = (595.28, 841.89)
_RECONSTRUCTION_NOTICE = "Maschinell rekonstruiertes und anonymisiertes Dokument"
_MIN_SEARCH_LENGTH = 3


class ExportError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def redacted_texts(entities: list[AppliedEntity]) -> list[str]:
    """Unique entity strings that must not appear in any output, longest first
    (so blackout of a full name is preferred over its parts)."""
    unique = {e.text.strip() for e in entities if e.status != SpanStatus.PRESERVED}
    return sorted((t for t in unique if len(t) >= _MIN_SEARCH_LENGTH), key=len, reverse=True)


# --- Native PDFs: rasterize + exact char-box blackout ------------------------


def redact_native_pdf(data: bytes, entities: list[AppliedEntity], settings: Settings) -> bytes:
    import pypdfium2 as pdfium
    from PIL import ImageDraw

    needles = redacted_texts(entities)
    scale = settings.VISION_OCR_RENDER_SCALE
    found: set[str] = set()

    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ExportError("The PDF could not be opened for export.", status_code=415) from exc
    try:
        images = []
        for page in document:
            page_width, page_height = page.get_size()
            textpage = page.get_textpage()
            boxes: list[tuple[float, float, float, float]] = []
            for needle in needles:
                for start, count in _search_all(textpage, needle):
                    found.add(needle)
                    boxes.extend(_char_rects(textpage, start, count))
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            draw = ImageDraw.Draw(image)
            padding = 1.5
            for left, bottom, right, top in boxes:
                draw.rectangle(
                    (
                        (left - padding) * scale,
                        (page_height - top - padding) * scale,
                        (right + padding) * scale,
                        (page_height - bottom + padding) * scale,
                    ),
                    fill="black",
                )
            images.append(image.convert("RGB"))
            textpage.close()
            page.close()
    finally:
        document.close()

    missing = [needle for needle in needles if needle not in found and not _covered(needle, found)]
    if missing:
        # Fail closed: the text layer diverges from what we extracted, so a
        # blackout might be incomplete. Never emit a possibly leaky PDF.
        raise ExportError(
            f"{len(missing)} redacted item(s) could not be located in the PDF text "
            "layer; the redacted PDF was NOT generated. The anonymized text "
            "download remains safe to use."
        )
    if not images:
        raise ExportError("The PDF contains no pages.", status_code=415)

    buffer = io.BytesIO()
    images[0].save(
        buffer,
        format="PDF",
        save_all=True,
        append_images=images[1:],
        resolution=72 * scale,
    )
    return buffer.getvalue()


def _search_all(textpage, needle: str) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    for variant in _needle_variants(needle):
        searcher = textpage.search(variant, match_case=True)
        while True:
            result = searcher.get_next()
            if result is None:
                break
            matches.append(result)
        searcher.close()
        if matches:
            break
    return matches


def _needle_variants(needle: str) -> list[str]:
    """The needle itself, plus a whitespace-collapsed variant (pdfium joins
    line-wrapped text with single spaces)."""
    collapsed = re.sub(r"\s+", " ", needle).strip()
    variants = [needle]
    if collapsed != needle:
        variants.append(collapsed)
    return variants


def _covered(needle: str, found: set[str]) -> bool:
    """A shorter needle is fine if it only occurs inside an already-found one
    (e.g. name parts of a full name)."""
    return any(needle in longer for longer in found if longer != needle)


def _char_rects(textpage, start: int, count: int) -> list[tuple[float, float, float, float]]:
    """Merge the char boxes of a match into per-line rectangles."""
    rects: list[list[float]] = []
    for index in range(start, start + count):
        box = textpage.get_charbox(index)
        if box is None:
            continue
        left, bottom, right, top = box
        if right - left <= 0 or top - bottom <= 0:
            continue
        for rect in rects:
            # Same visual line → extend.
            if abs(rect[1] - bottom) < 2 and abs(rect[3] - top) < 2:
                rect[0] = min(rect[0], left)
                rect[2] = max(rect[2], right)
                break
        else:
            rects.append([left, bottom, right, top])
    return [tuple(rect) for rect in rects]


# --- Scanned PDFs: layout-faithful rebuild from anonymized text --------------


def rebuild_scanned_pdf(
    source_text: str,
    layout: list[LayoutLine],
    entities: list[AppliedEntity],
    page_count: int,
) -> bytes:
    from reportlab.lib.colors import grey
    from reportlab.pdfgen import canvas

    if not layout:
        raise ExportError(
            "No layout information is available for this document; "
            "re-run the anonymization and export again."
        )

    width, height = _PAGE_A4
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=_PAGE_A4)
    pages = max(page_count, max(line.page_number for line in layout))

    for page_number in range(1, pages + 1):
        pdf.setFillColor(grey)
        pdf.setFont("Helvetica-Oblique", 7)
        pdf.drawString(24, height - 16, _RECONSTRUCTION_NOTICE)
        pdf.setFillColorRGB(0, 0, 0)
        for line in layout:
            if line.page_number != page_number:
                continue
            text = anonymize_line(source_text, line.start, line.end, entities)
            if not text.strip():
                continue
            font_size = min(max((line.y2 - line.y1) / 1000 * height * 0.75, 6.0), 16.0)
            x = line.x1 / 1000 * width
            y = height - (line.y2 / 1000 * height)
            pdf.setFont("Helvetica", font_size)
            pdf.drawString(x, y, _latin1_safe(text))
        pdf.showPage()
    pdf.save()
    output = buffer.getvalue()

    _verify_rebuilt(output, entities)
    return output


def anonymize_line(
    source_text: str, line_start: int, line_end: int, entities: list[AppliedEntity]
) -> str:
    """Apply entity replacements to one line (identified by source offsets).

    An entity that spans line boundaries shows its replacement on the line it
    starts in; continuation lines skip the covered characters."""
    parts: list[str] = []
    position = line_start
    for entity in sorted(entities, key=lambda e: e.start):
        if entity.replacement is None or entity.end <= line_start or entity.start >= line_end:
            continue
        if entity.start > position:
            parts.append(source_text[position : entity.start])
        if entity.start >= line_start:
            parts.append(entity.replacement)
        position = min(entity.end, line_end)
        if entity.end > line_end:
            break
    if position < line_end:
        parts.append(source_text[position:line_end])
    return "".join(parts)


def _latin1_safe(text: str) -> str:
    """Helvetica covers latin-1 (incl. äöüß); replace anything else."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _verify_rebuilt(output: bytes, entities: list[AppliedEntity]) -> None:
    """Re-extract the generated PDF and assert no redacted string survived."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(output))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    collapsed = re.sub(r"\s+", " ", extracted)
    for needle in redacted_texts(entities):
        if needle in extracted or re.sub(r"\s+", " ", needle) in collapsed:
            raise ExportError(
                "Verification failed: a redacted string is still present in the "
                "rebuilt PDF; the export was aborted."
            )
