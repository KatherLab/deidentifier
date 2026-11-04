"""SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION."""

from backend.src.utils.layout import LayoutLine, PageRange, complete_layout


def _covered(text: str, layout: list[LayoutLine]) -> str:
    return "".join(text[line.start : line.end] for line in sorted(layout, key=lambda x: x.start))


def _box(page: int, start: int, end: int, y: int = 100) -> LayoutLine:
    return LayoutLine(page_number=page, x1=100, y1=y, x2=900, y2=y + 20, start=start, end=end)


def test_fully_boxed_document_is_returned_unchanged():
    text = "Erste Zeile\nZweite Zeile\n\nDritte Zeile"
    pages = [PageRange(page_number=1, start=0, end=24), PageRange(page_number=2, start=26, end=38)]
    layout = [_box(1, 0, 11), _box(1, 12, 24, y=130), _box(2, 26, 38)]

    assert complete_layout(text, pages, layout) == layout


def test_text_without_boxes_is_placed_in_reading_order():
    text = "Erste Zeile\n\nZweite Zeile\nDritte Zeile"

    layout = complete_layout(text, [], [])

    assert [text[line.start : line.end] for line in layout] == [
        "Erste Zeile",
        "Zweite Zeile",
        "Dritte Zeile",
    ]
    assert layout[0].y2 <= layout[1].y1 and layout[1].y2 <= layout[2].y1
    assert all(line.page_number == 1 for line in layout)


def test_blank_text_yields_no_layout():
    assert complete_layout(" \n\n ", [], []) == []


def test_long_line_wraps_without_losing_a_character():
    text = "Der Patient wurde stationaer aufgenommen und behandelt. " * 20

    layout = complete_layout(text, [], [])

    assert len(layout) > 1
    assert _covered(text, layout) == text
    assert all(a.end == b.start for a, b in zip(layout, layout[1:], strict=False))


def test_word_wider_than_the_line_is_split():
    text = "X" * 500

    layout = complete_layout(text, [], [])

    assert len(layout) > 1
    assert _covered(text, layout) == text


def test_overflow_continues_on_inserted_page_and_moves_later_pages_back():
    first = "\n".join(f"Zeile {index}" for index in range(200))
    second = "Letzte Seite"
    text = f"{first}\n\n{second}"
    pages = [
        PageRange(page_number=1, start=0, end=len(first)),
        PageRange(page_number=2, start=len(first) + 2, end=len(text)),
    ]
    boxed_second = _box(2, len(first) + 2, len(text))

    layout = complete_layout(text, pages, [boxed_second])

    used = {line.page_number for line in layout if line.end <= len(first)}
    assert max(used) > 1
    last = next(line for line in layout if line.start == boxed_second.start)
    assert last.page_number == max(used) + 1
    assert (last.y1, last.y2) == (boxed_second.y1, boxed_second.y2)
    assert all(0 <= line.y1 < line.y2 <= 1000 for line in layout)


def test_page_without_boxes_among_boxed_pages_keeps_its_text():
    """The flat fallback prompt returns unboxed lines for just that one page."""
    text = "Seite eins\n\nSeite zwei ohne Boxen"
    pages = [PageRange(page_number=1, start=0, end=10), PageRange(page_number=2, start=12, end=33)]

    layout = complete_layout(text, pages, [_box(1, 0, 10)])

    assert [(line.page_number, text[line.start : line.end]) for line in layout] == [
        (1, "Seite eins"),
        (2, "Seite zwei ohne Boxen"),
    ]


def test_unboxed_line_on_a_boxed_page_goes_below_the_boxes():
    text = "Mit Box\nOhne Box"
    pages = [PageRange(page_number=1, start=0, end=len(text))]
    boxed = _box(1, 0, 7, y=300)

    layout = complete_layout(text, pages, [boxed])

    stray = next(line for line in layout if text[line.start : line.end] == "Ohne Box")
    assert stray.y1 > boxed.y2
    assert boxed in layout
