"""Async HTTP client for a docling-serve instance (adapted from llmaixweb).

Used for high-quality PDF text extraction and for Tesseract OCR of scanned
PDFs. The multipart /v1/convert/file endpoint is used; responses return
Markdown, which is good enough as anonymization input text.
"""

import httpx


class DoclingServeError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        if status_code:
            message = f"{message} (HTTP {status_code})"
        super().__init__(message)


class DoclingServeClient:
    def __init__(self, base_url: str, timeout_seconds: int = 600):
        if not base_url:
            raise DoclingServeError("docling-serve base URL is required")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def convert_pdf(
        self,
        file_content: bytes,
        filename: str,
        *,
        do_ocr: bool,
        force_ocr: bool = False,
    ) -> str:
        """Convert a PDF to text; with do_ocr=True Tesseract OCR is used."""
        endpoint = f"{self.base_url}/v1/convert/file"
        files = {"files": (filename, file_content, "application/pdf")}
        data: dict[str, str] = {
            "from_formats": "pdf",
            "to_formats": "md",
            "do_ocr": str(do_ocr).lower(),
            "force_ocr": str(force_ocr).lower(),
            "table_mode": "fast",
            "abort_on_error": "false",
        }
        if do_ocr:
            data["ocr_preset"] = "tesseract"
        else:
            data["image_export_mode"] = "placeholder"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(endpoint, files=files, data=data)
        except httpx.TimeoutException as exc:
            raise DoclingServeError(
                f"docling-serve request timed out after {self.timeout_seconds}s"
            ) from exc
        except httpx.RequestError as exc:
            raise DoclingServeError("docling-serve is unreachable") from exc

        if response.status_code != 200:
            raise DoclingServeError(
                "docling-serve returned an error", status_code=response.status_code
            )
        return _extract_text(response.json())


def _extract_text(response_json: dict) -> str:
    """Extract text from a docling-serve response (schema varies by version)."""
    document = response_json.get("document")
    candidates = [response_json, document if isinstance(document, dict) else {}]
    for container in candidates:
        for key in ("md_content", "markdown", "text_content", "text", "content"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise DoclingServeError("docling-serve response contained no text")
