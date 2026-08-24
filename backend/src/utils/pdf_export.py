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

Both verifications compare against the anonymized TEXT output (`expected_text`)
rather than against an empty page, because the two are not the same claim:

* A redacted string that survives in the PDF but NOT in the text output means
  a blackout was not applied — the export machinery failed. Refused, always.
* A redacted string that survives in BOTH is the reviewer's own doing: they
  kept one of several identical passages, or a detector found only one
  occurrence of it. The PDF is then exactly as redacted as the text download
  the user already has, and `leakage.py` has already flagged it as a HIGH
  residual. Refused with `forceable=True` so the UI can offer "export anyway"
  — never exported silently.
"""

import base64
import io
import re

from ..core.config import Settings
from ..schemas.anonymize import RedactArea
from ..schemas.entities import AppliedEntity, SpanStatus
from .extraction import LayoutLine
from .safe_logging import get_safe_logger

logger = get_safe_logger(__name__)

_PAGE_A4 = (595.28, 841.89)
_RECONSTRUCTION_NOTICE = "Maschinell rekonstruiertes und anonymisiertes Dokument"
_MIN_SEARCH_LENGTH = 2
# Needles up to this length (e.g. an age "28") are matched as WHOLE WORDS:
# substring search would black out every embedded occurrence ("2028"), while
# dropping them entirely would leak the entity in the exported PDF.
_SHORT_NEEDLE_MAX = 3


# Stable codes for the export failures the UI reacts to, mirrored under
# `errors.export.*` in the locale catalogs.
EXPORT_FAILED = "pdf_export_failed"
RESIDUAL_EXPLAINED = "pdf_export_residual_explained"
RESIDUAL_UNEXPLAINED = "pdf_export_residual_unexplained"
NOT_LOCATED = "pdf_export_not_located"
AREA_RESIDUAL = "pdf_export_area_residual"

# Cap on the residual strings echoed back to the client. They are document
# content: the client already holds the source text and the entity list, so
# this is nothing new to it — but it never goes to a log.
_MAX_REPORTED_RESIDUALS = 20


class ExportError(Exception):
    """`code` is stable and translated by the UI. `forceable` marks the one
    failure the reviewer may overrule (see the module docstring); `items` are
    the strings that would stay visible, so the confirmation can name them.

    `count` is how many there are, which is NOT `len(items)` once the list is
    capped for display — a notice that says "20" about 37 findings understates
    exactly the thing it exists to state."""

    def __init__(
        self,
        message: str,
        status_code: int = 422,
        *,
        code: str = EXPORT_FAILED,
        forceable: bool = False,
        items: list[str] | None = None,
        count: int | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.forceable = forceable
        self.items = items or []
        self.count = len(self.items) if count is None else count


def _page_areas(
    areas: list[RedactArea] | None, page_number: int
) -> list[tuple[float, float, float, float]]:
    """Absolute-fraction rects (x0, y0, x1, y1 in 0–1, top-left origin) of the
    user-drawn areas on ONE page (1-based)."""
    if not areas:
        return []
    return [
        (area.x0 / 1000, area.y0 / 1000, area.x1 / 1000, area.y1 / 1000)
        for area in areas
        if area.page == page_number
    ]


def redacted_texts(entities: list[AppliedEntity]) -> list[str]:
    """Unique entity strings that must not appear in any output, longest first
    (so blackout of a full name is preferred over its parts)."""
    unique = {e.text.strip() for e in entities if e.status != SpanStatus.PRESERVED}
    return sorted((t for t in unique if len(t) >= _MIN_SEARCH_LENGTH), key=len, reverse=True)


def preserved_texts_at_risk(entities: list[AppliedEntity]) -> list[str]:
    """Preserved passages that a native-PDF export will black out regardless.

    True redaction has no offsets to work with: it locates each redacted string
    by SEARCHING every page for it (`redacted_texts` above), so every occurrence
    goes black — including one the reviewer deliberately kept. The text output,
    applied by offset, keeps that occurrence. Without this the two exports of
    the same reviewed document disagree and nothing says so.

    The needle list comes from `redacted_texts` itself, so this cannot drift
    from what the exporter actually searches for. Matching is case-insensitive
    and substring-wise, mirroring `search_for`; that errs toward warning, which
    is the right direction for a notice about over-redaction.

    Only meaningful for native PDFs. The scanned-PDF reconstruction rebuilds
    each line through `anonymize_line`, which is offset-based and keeps a
    single preserved occurrence correctly.
    """
    needles = [needle.casefold() for needle in redacted_texts(entities)]
    if not needles:
        return []
    at_risk = {
        entity.text.strip()
        for entity in entities
        if entity.status == SpanStatus.PRESERVED
        and any(needle in entity.text.strip().casefold() for needle in needles)
    }
    return sorted(at_risk)


def _apply_areas(data: bytes, areas: list[RedactArea] | None) -> bytes:
    """Apply the user-drawn areas to a PDF as TRUE redactions: the text and the
    image pixels under each rectangle are removed, not merely covered.

    Painting a filled rectangle over the page (what a drawing API does) leaves
    everything underneath selectable and extractable — the box would hide the
    content from the eye only. Verified below, and never silently skipped."""
    if not areas:
        return data

    import pymupdf

    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        for page in document:
            page_width, page_height = page.rect.width, page.rect.height
            rects = [
                pymupdf.Rect(x0 * page_width, y0 * page_height, x1 * page_width, y1 * page_height)
                for x0, y0, x1, y1 in _page_areas(areas, page.number + 1)
            ]
            if not rects:
                continue
            for rect in rects:
                page.add_redact_annot(rect, fill=(0, 0, 0))
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
        output = document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()

    _verify_areas(output, areas)
    return output


def _verify_areas(data: bytes, areas: list[RedactArea] | None) -> None:
    """Mandatory: no text may survive inside a user-drawn area."""
    if not areas:
        return

    import pymupdf

    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        for page in document:
            page_width, page_height = page.rect.width, page.rect.height
            for x0, y0, x1, y1 in _page_areas(areas, page.number + 1):
                rect = pymupdf.Rect(
                    x0 * page_width, y0 * page_height, x1 * page_width, y1 * page_height
                )
                if any(word[4].strip() for word in page.get_text("words", clip=rect)):
                    raise ExportError(
                        "Verification failed: text is still present under a blacked-out "
                        "area; the redacted PDF was NOT generated.",
                        code=AREA_RESIDUAL,
                    )
    finally:
        document.close()


def _compact(text: str) -> str:
    """Strip ALL whitespace. The detector reads the PDF via one extractor
    (docling-serve or pypdf) while the export searches it via another (pymupdf /
    pdfium); those extractors inject or drop spaces around kerned glyphs
    differently, so an entity string detected as `A-BB2F-C` can appear as
    `A- BB2F -C` in the export's text layer. Comparing whitespace-stripped forms
    makes locating and verification robust to that divergence."""
    return re.sub(r"\s+", "", text)


# --- Native PDFs -------------------------------------------------------------
#
# Primary path: TRUE redaction with PyMuPDF — the redacted text is removed
# from the content stream (and image pixels under the boxes erased), the rest
# of the document stays a genuine vector PDF with a selectable, searchable
# text layer. Verified by re-extraction; any failure falls back to the
# rasterize+blackout path, which physically cannot carry a text layer.


def redact_native_pdf(
    data: bytes,
    entities: list[AppliedEntity],
    settings: Settings,
    areas: list[RedactArea] | None = None,
    *,
    expected_text: str = "",
    force: bool = False,
) -> bytes:
    try:
        return _redact_native_true(
            data, entities, settings, areas, expected_text=expected_text, force=force
        )
    except ExportError as exc:
        if exc.forceable:
            # Not a machinery failure — the rasterizer would black out the same
            # passages and stop on the same finding, only after a full render,
            # and its own error would hide the one the reviewer can act on.
            raise
        logger.warning("true_redaction_fallback", reason=type(exc).__name__)
    except Exception as exc:
        logger.warning("true_redaction_fallback", reason=type(exc).__name__)
    return _redact_native_raster(data, entities, settings, areas)


def _redact_native_true(
    data: bytes,
    entities: list[AppliedEntity],
    settings: Settings,
    areas: list[RedactArea] | None = None,
    *,
    expected_text: str = "",
    force: bool = False,
) -> bytes:
    import pymupdf

    needles = redacted_texts(entities)
    replacements = {
        e.text.strip(): e.replacement
        for e in entities
        if e.status == SpanStatus.GENERALIZED and e.replacement
    }
    found: set[str] = set()

    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        for page in document:
            for needle in needles:
                if len(needle) <= _SHORT_NEEDLE_MAX:
                    rects = _short_word_rects(page, needle)
                else:
                    rects = []
                    for variant in _needle_variants(needle):
                        rects = page.search_for(variant)
                        if rects:
                            break
                    if not rects:
                        # search_for can't bridge whitespace the text layer
                        # injected around kerned glyphs; retry ignoring spaces.
                        rects = _ws_insensitive_word_rects(page, needle)
                if not rects:
                    continue
                found.add(needle)
                replacement = replacements.get(needle)
                for rect in rects:
                    if replacement:
                        page.add_redact_annot(
                            rect,
                            text=replacement,
                            fill=(1, 1, 1),
                            text_color=(0, 0, 0),
                            fontsize=max(min(rect.height * 0.8, 12.0), 6.0),
                        )
                    else:
                        page.add_redact_annot(rect, fill=(0, 0, 0))
            # User-drawn areas (signatures, logos, stamps): black box over the
            # region; apply_redactions also removes text and image pixels
            # underneath. fitz page coordinates share the top-left origin of
            # the normalized area coordinates.
            page_width, page_height = page.rect.width, page.rect.height
            for x0, y0, x1, y1 in _page_areas(areas, page.number + 1):
                page.add_redact_annot(
                    pymupdf.Rect(
                        x0 * page_width, y0 * page_height, x1 * page_width, y1 * page_height
                    ),
                    fill=(0, 0, 0),
                )
            # Remove the text AND erase image pixels under the boxes (a
            # "native" PDF can embed scanned fragments containing PII).
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
            for annot in list(page.annots() or []):
                page.delete_annot(annot)

        missing = [n for n in needles if n not in found and not _covered(n, found)]
        if missing:
            raise ExportError(
                f"{len(missing)} redacted item(s) could not be located in the PDF text "
                "layer; the redacted PDF was NOT generated.",
                code=NOT_LOCATED,
            )

        # Scrub metadata, XMP, embedded/attached files, JavaScript, hidden text.
        try:
            document.scrub()
        except Exception:
            document.set_metadata({})
            document.del_xml_metadata()
        output = document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()

    _verify_native(output, needles, expected_text, force)
    _verify_areas(output, areas)
    return output


def _short_word_rects(page, needle: str) -> list:
    """Whole-word rects for short needles via the page's word list."""
    import pymupdf

    rects = []
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        if word.strip(".,;:()[]{}\"'") == needle:
            rects.append(pymupdf.Rect(x0, y0, x1, y1))
    return rects


def _ws_insensitive_word_rects(page, needle: str) -> list:
    """Locate a needle whose whitespace differs from the PDF's text layer, by
    matching against the page's words concatenated WITHOUT separators. Returns
    the boxes of every word that overlaps a match. A word only partially covered
    by the needle is redacted whole — over-redaction, never a leak."""
    import pymupdf

    target = _compact(needle)
    if len(target) < _MIN_SEARCH_LENGTH:
        return []
    spans: list[tuple[int, int, object]] = []
    haystack = ""
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        spans.append((len(haystack), len(haystack) + len(word), pymupdf.Rect(x0, y0, x1, y1)))
        haystack += word
    rects: list = []
    pos = haystack.find(target)
    while pos >= 0:
        end = pos + len(target)
        rects.extend(rect for start, stop, rect in spans if start < end and stop > pos)
        pos = haystack.find(target, end)
    return rects


def _needle_survives(needle: str, text: str, collapsed: str, compact: str | None = None) -> bool:
    """Word-bounded check for short needles (so '2028' never counts as a
    surviving '28'), substring check otherwise. Long needles also match against
    the whitespace-stripped text, so an occurrence the text layer split with
    injected spaces still counts as surviving (fail-closed, never a silent
    leak)."""
    if len(needle) <= _SHORT_NEEDLE_MAX:
        pattern = rf"(?<!\w){re.escape(needle)}(?!\w)"
        return bool(re.search(pattern, text) or re.search(pattern, collapsed))
    if needle in text or re.sub(r"\s+", " ", needle) in collapsed:
        return True
    compact = _compact(text) if compact is None else compact
    return _compact(needle) in compact


def _surviving(needles: list[str], text: str) -> list[str]:
    """The needles that are still present in `text`, in the given order."""
    collapsed = re.sub(r"\s+", " ", text)
    compact = _compact(text)
    return [needle for needle in needles if _needle_survives(needle, text, collapsed, compact)]


def _check_residuals(
    output_text: str,
    needles: list[str],
    expected_text: str,
    force: bool,
    location: str,
) -> None:
    """Classify the redacted strings that survived in the exported PDF.

    Split by whether the anonymized TEXT output has them too (see the module
    docstring): one is the reviewer's decision, the other is a broken export.
    An empty `expected_text` means "nothing may survive", the strict default
    for callers that have no text output to compare against."""
    surviving = _surviving(needles, output_text)
    if not surviving:
        return

    explained = set(_surviving(surviving, expected_text)) if expected_text else set()
    unexplained = [needle for needle in surviving if needle not in explained]
    if unexplained:
        # Not in the text output, so no reviewer decision put it there: a
        # blackout that should have covered it did not. Never forceable.
        raise ExportError(
            f"Verification failed: a redacted string is still present in the {location}; "
            "the export was aborted.",
            code=RESIDUAL_UNEXPLAINED,
        )

    if not force:
        raise ExportError(
            f"{len(surviving)} redacted text(s) also occur outside the passages that were "
            "redacted and therefore stay visible in the PDF — exactly as they do in the "
            "anonymized text. The PDF was not generated; confirm to export it anyway.",
            code=RESIDUAL_EXPLAINED,
            forceable=True,
            items=surviving[:_MAX_REPORTED_RESIDUALS],
            count=len(surviving),
        )

    logger.warning("export_forced_residuals", count=len(surviving), location=location)


def _verify_native(
    output: bytes, needles: list[str], expected_text: str = "", force: bool = False
) -> None:
    """Mandatory: re-extract the redacted PDF and assert no redacted string
    survived anywhere in the remaining text layer."""
    import pymupdf

    document = pymupdf.open(stream=output, filetype="pdf")
    try:
        text = "\n".join(page.get_text() for page in document)
    finally:
        document.close()
    _check_residuals(text, needles, expected_text, force, "redacted PDF's text layer")


def _redact_native_raster(
    data: bytes,
    entities: list[AppliedEntity],
    settings: Settings,
    areas: list[RedactArea] | None = None,
) -> bytes:
    import pypdfium2 as pdfium
    from PIL import ImageDraw, ImageFont

    needles = redacted_texts(entities)
    # GENERALIZED entities (e.g. birth date → year) are not blacked out but
    # erased and replaced with their generalized value, mirroring the text
    # output ("Date of Birth: 1996" instead of a black bar).
    replacements = {
        e.text.strip(): e.replacement
        for e in entities
        if e.status == SpanStatus.GENERALIZED and e.replacement
    }
    scale = settings.VISION_OCR_RENDER_SCALE
    found: set[str] = set()

    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ExportError("The PDF could not be opened for export.", status_code=415) from exc
    try:
        images = []
        for page_index, page in enumerate(document):
            page_width, page_height = page.get_size()
            textpage = page.get_textpage()
            boxes: list[tuple[float, float, float, float, str | None]] = []
            for needle in needles:
                replacement = replacements.get(needle)
                matches = _search_all(textpage, needle)
                if len(needle) <= _SHORT_NEEDLE_MAX:
                    matches = [m for m in matches if _pdfium_word_bounded(textpage, m)]
                elif not matches:
                    # search can't bridge whitespace the text layer injected
                    # around kerned glyphs; retry ignoring spaces.
                    matches = _ws_insensitive_char_matches(textpage, needle)
                for start, count in matches:
                    found.add(needle)
                    for rect in _char_rects(textpage, start, count):
                        boxes.append((*rect, replacement))
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            draw = ImageDraw.Draw(image)
            padding = 1.5
            for left, bottom, right, top, replacement in boxes:
                pixel_box = (
                    (left - padding) * scale,
                    (page_height - top - padding) * scale,
                    (right + padding) * scale,
                    (page_height - bottom + padding) * scale,
                )
                if replacement is None:
                    draw.rectangle(pixel_box, fill="black")
                else:
                    draw.rectangle(pixel_box, fill="white")
                    box_height = pixel_box[3] - pixel_box[1]
                    size = max(int(box_height * 0.9), 10)
                    font = ImageFont.load_default(size=size)
                    draw.text(
                        (pixel_box[0] + 2, pixel_box[1] + box_height * 0.05),
                        replacement,
                        fill="black",
                        font=font,
                    )
            # User-drawn areas: black box over the rendered pixels (the
            # rendered image shares the top-left origin of the coordinates).
            for x0, y0, x1, y1 in _page_areas(areas, page_index + 1):
                draw.rectangle(
                    (
                        x0 * page_width * scale,
                        y0 * page_height * scale,
                        x1 * page_width * scale,
                        y1 * page_height * scale,
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


def _pdfium_word_bounded(textpage, match: tuple[int, int]) -> bool:
    start, count = match
    before = textpage.get_text_range(start - 1, 1) if start > 0 else ""
    after = textpage.get_text_range(start + count, 1) or ""
    return not (before[-1:].isalnum() or after[:1].isalnum())


def _ws_insensitive_char_matches(textpage, needle: str) -> list[tuple[int, int]]:
    """Locate a needle whose whitespace differs from pdfium's text layer, by
    matching against the page's characters with whitespace removed. Returns
    (start, count) char-index spans covering the exact visible glyphs of each
    occurrence (interior whitespace chars are included in the span; their empty
    boxes are simply skipped when the rects are built)."""
    target = _compact(needle)
    if len(target) < _MIN_SEARCH_LENGTH:
        return []
    orig_index: list[int] = []
    compact_chars: list[str] = []
    for index in range(textpage.count_chars()):
        char = textpage.get_text_range(index, 1)
        if char and not char.isspace():
            compact_chars.append(char)
            orig_index.append(index)
    haystack = "".join(compact_chars)
    matches: list[tuple[int, int]] = []
    pos = haystack.find(target)
    while pos >= 0:
        start = orig_index[pos]
        end = orig_index[pos + len(target) - 1]
        matches.append((start, end - start + 1))
        pos = haystack.find(target, pos + len(target))
    return matches


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
    """Merge the char boxes of a match into per-line rectangles.

    Loose char boxes are uniform full line-height cells (ascent to descent for
    every character), so bars stay level regardless of descenders (y, g, p) —
    tight glyph boxes would dip for those letters and even split one word into
    bars of different heights."""
    rects: list[list[float]] = []
    for index in range(start, start + count):
        try:
            box = textpage.get_charbox(index, loose=True)
        except Exception:
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


# --- Page rendering for the area-redaction editor ----------------------------

_PAGE_RENDER_SCALE = 2.0
# Render cap: clinical letters are short; huge documents would blow up the
# JSON response. The UI states when pages were skipped.
_MAX_RENDER_PAGES = 40


def render_pdf_pages(data: bytes) -> tuple[list[dict], bool]:
    """Render the pages of an uploaded PDF as PNG data URLs for the frontend
    area-redaction editor, plus the bounding boxes of embedded images
    (one-click redaction suggestions). Returns (pages, truncated). Nothing is
    persisted server-side."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ExportError("The PDF could not be opened.", status_code=415) from exc

    pages: list[dict] = []
    try:
        total = len(document)
        if total == 0:
            raise ExportError("The PDF contains no pages.", status_code=415)
        for index in range(min(total, _MAX_RENDER_PAGES)):
            page = document[index]
            width, height = page.get_size()
            image = page.render(scale=_PAGE_RENDER_SCALE).to_pil().convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")

            # Embedded-image bounds: pdfium page coordinates have a
            # bottom-left origin; normalized coordinates are top-left.
            boxes: list[dict] = []
            for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,)):
                left, bottom, right, top = obj.get_bounds()
                box = {
                    "x0": max(left / width * 1000, 0.0),
                    "y0": max((height - top) / height * 1000, 0.0),
                    "x1": min(right / width * 1000, 1000.0),
                    "y1": min((height - bottom) / height * 1000, 1000.0),
                }
                if box["x1"] > box["x0"] and box["y1"] > box["y0"]:
                    boxes.append(box)

            pages.append(
                {
                    "page": index + 1,
                    "width": width,
                    "height": height,
                    "image": "data:image/png;base64,"
                    + base64.b64encode(buffer.getvalue()).decode("ascii"),
                    "image_boxes": boxes,
                }
            )
        return pages, total > _MAX_RENDER_PAGES
    finally:
        document.close()


# --- Scanned PDFs: layout-faithful rebuild from anonymized text --------------


def rebuild_scanned_pdf(
    source_text: str,
    layout: list[LayoutLine],
    entities: list[AppliedEntity],
    page_count: int,
    areas: list[RedactArea] | None = None,
    bars: bool = False,
    *,
    expected_text: str = "",
    force: bool = False,
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
    bar_tokens = _bar_tokens(entities) if bars else []

    for page_number in range(1, pages + 1):
        pdf.setFillColor(grey)
        pdf.setFont("Helvetica-Oblique", 7)
        pdf.drawString(24, height - 16, _RECONSTRUCTION_NOTICE)
        pdf.setFillColorRGB(0, 0, 0)
        for line in layout:
            if line.page_number != page_number:
                continue
            text = _latin1_safe(anonymize_line(source_text, line.start, line.end, entities))
            if not text.strip():
                continue
            box_width = max((line.x2 - line.x1) / 1000 * width, 30.0)
            box_height = max((line.y2 - line.y1) / 1000 * height, 8.0)
            font_size, wrapped = _fit_text(text, box_width, box_height)
            x = line.x1 / 1000 * width
            top = line.y1 / 1000 * height
            pdf.setFont("Helvetica", font_size)
            for index, wrapped_line in enumerate(wrapped):
                baseline = height - top - (index + 1) * font_size * _LINE_SPACING + font_size * 0.2
                pdf.drawString(x, baseline, wrapped_line)
                if bar_tokens:
                    _draw_bars(pdf, wrapped_line, bar_tokens, x, baseline, font_size)
        pdf.showPage()
    pdf.save()
    output = buffer.getvalue()

    # User-drawn areas are applied to the REBUILT page (the geometry the review
    # UI draws on), as true redactions — a filled rectangle painted over the
    # text would leave that text selectable underneath.
    output = _apply_areas(output, areas)

    _verify_rebuilt(output, entities, expected_text, force)
    return output


_LINE_SPACING = 1.25
_FONT_CANDIDATES = (11.0, 10.0, 9.0, 8.0, 7.0, 6.0)

# How far a bar reaches below and above the baseline, as a share of the font
# size, plus the horizontal padding that makes it read as a bar rather than a
# tight box around the token. Sized to the text line rather than to the glyphs,
# which is what the native export's boxes cover — the two should look alike.
_BAR_DESCENT = 0.25
_BAR_ASCENT = 0.95
_BAR_PADDING = 0.12


def _bar_tokens(entities: list[AppliedEntity]) -> list[str]:
    """The replacement strings a black bar is drawn over, longest first.

    Mirrors the native export (`_redact_native_true`): everything it blacks out
    gets a bar here too, while a GENERALIZED replacement — a date reduced to its
    year — stays readable there and so stays readable here. PRESERVED entities
    keep their original text and are not replacements at all.
    """
    tokens = {
        _latin1_safe(entity.replacement)
        for entity in entities
        if entity.replacement
        and entity.status not in (SpanStatus.PRESERVED, SpanStatus.GENERALIZED)
    }
    return sorted(tokens, key=len, reverse=True)


def _draw_bars(pdf, text: str, tokens: list[str], x: float, baseline: float, size: float) -> None:
    """Black out every placeholder occurrence in one drawn line.

    The bar is painted OVER the placeholder, which stays in the text layer: the
    token is never sensitive (that is the point of it), and keeping it means a
    reader extracting the text still gets `[PERSON_1]` — including which person
    it was. Locating the tokens by searching the drawn string is exact, because
    this is the same string, font and size `drawString` just rendered, and
    placeholders contain no spaces, so wrapping can never split one.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    for token in tokens:
        position = text.find(token)
        while position != -1:
            padding = size * _BAR_PADDING
            start = x + stringWidth(text[:position], "Helvetica", size) - padding
            token_width = stringWidth(token, "Helvetica", size) + 2 * padding
            pdf.rect(
                start,
                baseline - size * _BAR_DESCENT,
                token_width,
                size * (_BAR_DESCENT + _BAR_ASCENT),
                fill=1,
                stroke=0,
            )
            position = text.find(token, position + len(token))


def _fit_text(text: str, box_width: float, box_height: float) -> tuple[float, list[str]]:
    """Choose a font size and wrap the text so it fits the OCR box.

    Unlimited-OCR emits paragraph-level boxes for wrapped text, so a "line"
    can be a whole paragraph: wrap it into as many lines as the box height
    allows instead of scaling the font to the box height."""
    from reportlab.lib.utils import simpleSplit

    for size in _FONT_CANDIDATES:
        if size > box_height:
            continue
        wrapped = simpleSplit(text, "Helvetica", size, box_width)
        if len(wrapped) * size * _LINE_SPACING <= box_height * 1.2:
            return size, wrapped
    size = _FONT_CANDIDATES[-1]
    return size, simpleSplit(text, "Helvetica", size, box_width)


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


# Common characters outside latin-1 that OCR output contains regularly.
_UNICODE_FALLBACKS = str.maketrans(
    {
        "•": "-",  # bullet
        "▪": "-",
        "–": "-",  # en dash
        "—": "-",  # em dash
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "…": "...",
        " ": " ",  # non-breaking space
        "→": "->",
    }
)


def _latin1_safe(text: str) -> str:
    """Helvetica covers latin-1 (incl. äöüß); map or replace anything else."""
    return text.translate(_UNICODE_FALLBACKS).encode("latin-1", errors="replace").decode("latin-1")


def _verify_rebuilt(
    output: bytes, entities: list[AppliedEntity], expected_text: str = "", force: bool = False
) -> None:
    """Re-extract the generated PDF and assert no redacted string survived.

    The rebuild types the anonymized text through `_latin1_safe`, so the
    comparison text goes through it too — otherwise a passage the reviewer
    kept would read as unexplained purely because an en dash became a hyphen
    on the page."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(output))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    _check_residuals(
        extracted,
        redacted_texts(entities),
        _latin1_safe(expected_text) if expected_text else "",
        force,
        "rebuilt PDF",
    )
