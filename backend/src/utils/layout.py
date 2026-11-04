"""Where each transcribed line goes on the reconstructed page of a scanned PDF.

Not every OCR path knows where its text sat: docling's output and the `plain`
vision dialect carry no boxes at all, and a vision page that needed the flat
fallback prompt carries none for that page. `complete_layout` gives such text a
position in reading order, so a reconstruction contains the whole transcript —
the same text the detectors saw and the reviewer checked.

Positions are derived from the SOURCE text, never from the anonymized text: a
reviewer's areas are drawn on this geometry, so it must not move when a later
override changes a replacement's length. A replacement that outgrows its line
is absorbed by the renderer's font fitting, with `_WRAP_HEADROOM` keeping that
the exception.
"""

import math

from pydantic import BaseModel


class PageRange(BaseModel):
    page_number: int
    start: int
    end: int


class LayoutLine(BaseModel):
    """A transcribed line with its normalized (0–1000, top-left origin)
    bounding box and its character range in the extracted text. Basis for the
    reconstructed redacted PDF of scanned documents."""

    page_number: int
    x1: int
    y1: int
    x2: int
    y2: int
    start: int
    end: int


_PAGE_WIDTH_PT = 595.28
_PAGE_HEIGHT_PT = 841.89
_FONT = "Helvetica"
_FONT_SIZE = 11.0
_LINE_SPACING = 1.25

# Normalized page coordinates. The top margin clears the reconstruction notice.
_LEFT = 80
_RIGHT = 920
_TOP = 50
_BOTTOM = 960
_LINE_HEIGHT = math.ceil(_FONT_SIZE * _LINE_SPACING / _PAGE_HEIGHT_PT * 1000)
_PARAGRAPH_GAP = _LINE_HEIGHT // 2

# Lines are wrapped short of the box, so a placeholder a little longer than the
# text it replaces still fits at the regular font size.
_WRAP_HEADROOM = 0.88
_WRAP_WIDTH_PT = (_RIGHT - _LEFT) / 1000 * _PAGE_WIDTH_PT * _WRAP_HEADROOM


def complete_layout(
    text: str, pages: list[PageRange], layout: list[LayoutLine]
) -> list[LayoutLine]:
    """`layout` plus a position for every line of `text` it does not cover.

    Text without a box is placed below a page's boxed lines, or from the top of
    a page that has none. What does not fit continues on an inserted page, and
    the pages after it move back by one. A document whose lines all have boxes
    comes back exactly as it went in. `pages` empty means a single range over
    the whole text, for engines that report no page mapping.
    """
    ranges = pages or [PageRange(page_number=1, start=0, end=len(text))]
    completed: list[LayoutLine] = []
    inserted_pages = 0
    for page_range in ranges:
        boxed = [line for line in layout if line.page_number == page_range.page_number]
        page = page_range.page_number + inserted_pages
        completed += [line.model_copy(update={"page_number": page}) for line in boxed]
        y = max(line.y2 for line in boxed) + _LINE_HEIGHT if boxed else _TOP

        position = page_range.start
        for source_line in text[page_range.start : page_range.end].split("\n"):
            start, end = position, position + len(source_line)
            position = end + 1
            if not source_line.strip():
                if y > _TOP:
                    y += _PARAGRAPH_GAP
                continue
            if any(line.start < end and start < line.end for line in boxed):
                continue
            for wrapped_start, wrapped_end in _wrap(text, start, end):
                if y + _LINE_HEIGHT > _BOTTOM:
                    page += 1
                    inserted_pages += 1
                    y = _TOP
                completed.append(
                    LayoutLine(
                        page_number=page,
                        x1=_LEFT,
                        y1=y,
                        x2=_RIGHT,
                        y2=y + _LINE_HEIGHT,
                        start=wrapped_start,
                        end=wrapped_end,
                    )
                )
                y += _LINE_HEIGHT
    return completed


def _wrap(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split one source line into contiguous ranges that each fit the width.

    Breaks after whitespace, and inside a word only when it is wider than the
    line. Contiguous on purpose: an entity is placed on the line its first
    character falls in, so no character of the line may belong to none."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    widths: dict[str, float] = {}

    def char_width(char: str) -> float:
        if char not in widths:
            drawable = char.encode("latin-1", errors="replace").decode("latin-1")
            widths[char] = stringWidth(drawable, _FONT, _FONT_SIZE)
        return widths[char]

    ranges: list[tuple[int, int]] = []
    line_start = start
    break_after = start
    width = 0.0
    for index in range(start, end):
        char = text[index]
        width += char_width(char)
        if width > _WRAP_WIDTH_PT and index > line_start:
            cut = break_after if break_after > line_start else index
            ranges.append((line_start, cut))
            line_start = cut
            width = sum(char_width(c) for c in text[cut : index + 1])
        if char.isspace():
            break_after = index + 1
    if text[line_start:end].strip():
        ranges.append((line_start, end))
    return ranges
