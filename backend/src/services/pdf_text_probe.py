"""Lightweight PDF embedded-text detection using pypdf.

Adapted from llmaixweb: decides whether a PDF has useful embedded text
(→ text extraction) or is likely scanned (→ OCR routing) without loading
any heavy conversion machinery.
"""

import io
import re

from pypdf import PdfReader


def has_embedded_text(
    file_content: bytes,
    *,
    min_chars: int = 100,
    max_pages_to_check: int = 8,
) -> bool:
    """Return True if the PDF appears to contain useful embedded text.

    For small PDFs all pages are checked; for larger PDFs evenly spaced pages
    are sampled. Exits early once enough useful text is found.
    """
    try:
        reader = PdfReader(io.BytesIO(file_content))
    except Exception:
        return False

    num_pages = len(reader.pages)
    if num_pages == 0:
        return False

    text_parts: list[str] = []
    for idx in _probe_page_indices(num_pages, max_pages_to_check):
        try:
            page_text = reader.pages[idx].extract_text() or ""
        except Exception:
            page_text = ""
        if page_text:
            text_parts.append(page_text)
        if _has_useful_text("\n".join(text_parts), min_chars=min_chars):
            return True
    return False


def _probe_page_indices(num_pages: int, max_pages_to_check: int) -> list[int]:
    if num_pages <= 0 or max_pages_to_check <= 0:
        return []
    if num_pages <= max_pages_to_check:
        return list(range(num_pages))
    if max_pages_to_check == 1:
        return [0]
    return sorted(
        {round(i * (num_pages - 1) / (max_pages_to_check - 1)) for i in range(max_pages_to_check)}
    )


def _has_useful_text(text: str, *, min_chars: int = 100) -> bool:
    """Strip formatting artifacts so page noise doesn't count as content."""
    if not text:
        return False
    cleaned = re.sub(r"[#*_`>\-|:\[\]\(\){}]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return len(cleaned) >= min_chars
