"""Build minimal valid PDFs in-memory for tests (no extra dependencies).

Text is placed with standard Helvetica Tj operators, which pypdf extracts
reliably. Use ASCII-only text (standard encoding has no umlauts)."""


def make_pdf(lines: list[str], *, empty_pages: int = 0) -> bytes:
    """One text page with the given lines, plus optionally empty pages."""
    objects: list[bytes] = []

    def escape(value: str) -> str:
        return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    content_parts = ["BT /F1 12 Tf 72 720 Td 16 TL"]
    for index, line in enumerate(lines):
        if index > 0:
            content_parts.append("T*")
        content_parts.append(f"({escape(line)}) Tj")
    content_parts.append("ET")
    content = " ".join(content_parts).encode("latin-1")

    page_count = 1 + empty_pages
    # Object numbering: 1 catalog, 2 pages, 3..N page objects, then content
    # streams (one for the text page, one shared empty for the rest), then font.
    first_page_obj = 3
    text_content_obj = first_page_obj + page_count
    empty_content_obj = text_content_obj + 1
    font_obj = empty_content_obj + 1

    kids = " ".join(f"{first_page_obj + i} 0 R" for i in range(page_count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    for i in range(page_count):
        content_ref = text_content_obj if i == 0 else empty_content_obj
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_ref} 0 R "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
            ).encode()
        )
    objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    objects.append(b"<< /Length 0 >>\nstream\n\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_scanned_pdf(pages: int = 2) -> bytes:
    """A PDF whose pages contain no extractable text (like a scan)."""
    pdf = make_pdf([""], empty_pages=pages - 1)
    return pdf
