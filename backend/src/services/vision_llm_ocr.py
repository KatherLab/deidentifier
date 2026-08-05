"""Vision-LLM OCR via any OpenAI-compatible endpoint (adapted from llmaixweb).

Designed for and tested with baidu/Unlimited-OCR served by vLLM, but works
with any vision model that transcribes page images: PDF pages are rendered to
PNG with pypdfium2, sent per page (concurrently, order preserved) as data
URLs, and the transcriptions are joined.

Fail-closed: if any single page fails, the whole document fails — a document
missing a page must never be reported as anonymized. A page that the primary
prompt transcribes to no text while it clearly has ink is retried once with the
fallback prompt (the layout parser sometimes classifies a whole page as one
image and emits nothing); if it is still empty, the document fails rather than
silently dropping the page.
"""

import asyncio
import base64
import io
import json
import re

import httpx
import openai

from ..core.config import Settings
from ..utils.concurrency import global_semaphore


class VisionOCRError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


# Model markup such as <|ref|>…<|/ref|> emitted with skip_special_tokens=false.
_SPECIAL_TOKENS = re.compile(r"<\|[^|>]{0,40}\|>")
# Unlimited-OCR line prefixes: element type + bounding box in 0–1000
# page-normalized coordinates (top-left origin), e.g.
# "text [112, 76, 681, 95]Patientin: …". The boxes drive the
# layout-preserving redacted-PDF reconstruction; the prefix itself is
# stripped from the text output.
_LAYOUT_LINE = re.compile(
    r"^([a-z_]{1,20}) \[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\](.*)$", re.IGNORECASE
)


# A rendered page whose dark-pixel fraction is below this is treated as blank:
# an empty transcription is then expected, not a dropped page.
_MIN_INK_FRACTION = 0.002


class TranscribedLine:
    """One output line: text plus optional normalized bounding box."""

    def __init__(self, text: str, box: tuple[int, int, int, int] | None = None):
        self.text = text
        self.box = box


def _has_text(lines: list["TranscribedLine"]) -> bool:
    """True if any parsed line carries actual text (an image-only page parses
    to a single boxed line with empty text — that counts as no text)."""
    return any(line.text.strip() for line in lines)


def _page_has_ink(image) -> bool:
    """True if the rendered page has more than a trivial fraction of dark
    pixels — i.e. it is not a blank/near-blank page. Used to decide whether an
    empty transcription is suspicious (dropped page) or expected (blank page)."""
    histogram = image.convert("L").histogram()
    total = sum(histogram) or 1
    dark = sum(histogram[:128])
    return dark / total > _MIN_INK_FRACTION


def parse_transcription(raw: str) -> list[TranscribedLine]:
    cleaned = _SPECIAL_TOKENS.sub("", raw).strip()
    lines: list[TranscribedLine] = []
    for line in cleaned.splitlines():
        match = _LAYOUT_LINE.match(line)
        if match:
            box = tuple(int(match.group(i)) for i in range(2, 6))
            lines.append(TranscribedLine(text=match.group(6), box=box))  # type: ignore[arg-type]
        elif line.strip():
            lines.append(TranscribedLine(text=line))
    return lines


class VisionOCRService:
    def __init__(self, settings: Settings):
        if not (settings.VISION_OCR_API_BASE and settings.VISION_OCR_MODEL):
            raise VisionOCRError(
                "OCR engine 'llm_vision' requires VISION_OCR_API_BASE and VISION_OCR_MODEL.",
                status_code=503,
            )
        self._settings = settings
        try:
            self._extra_body: dict = (
                json.loads(settings.VISION_OCR_EXTRA_BODY)
                if settings.VISION_OCR_EXTRA_BODY.strip()
                else {}
            )
        except json.JSONDecodeError as exc:
            raise VisionOCRError(
                "VISION_OCR_EXTRA_BODY is not valid JSON.", status_code=500
            ) from exc

    async def process_pdf(self, data: bytes, progress=None) -> list[list[TranscribedLine]]:
        """Return the parsed transcription (lines with boxes) per page, in order."""
        pages = self._render_pages(data)
        if not pages:
            raise VisionOCRError("The PDF contains no pages.", status_code=422)
        # Global slots: the page limit is a TOTAL across all documents in flight.
        semaphore = global_semaphore("vision_ocr", self._settings.VISION_OCR_MAX_CONCURRENT_PAGES)
        completed = 0
        if progress:
            progress("ocr", 0, len(pages))

        async def limited(page_number: int, png: bytes, has_ink: bool) -> list[TranscribedLine]:
            nonlocal completed
            async with semaphore:
                lines = await self._transcribe_with_fallback(page_number, png, has_ink)
            completed += 1
            if progress:
                progress("ocr", completed, len(pages))
            return lines

        return list(
            await asyncio.gather(
                *(
                    limited(number, png, has_ink)
                    for number, (png, has_ink) in enumerate(pages, start=1)
                )
            )
        )

    async def _transcribe_with_fallback(
        self, page_number: int, png: bytes, has_ink: bool
    ) -> list[TranscribedLine]:
        """Transcribe one page. If the primary prompt yields no text while the
        page clearly has ink, retry once with the fallback prompt; if it is
        still empty, fail closed rather than silently drop the page."""
        lines = parse_transcription(await self._transcribe_page(page_number, png))
        if _has_text(lines) or not has_ink:
            return lines

        fallback_prompt = self._settings.VISION_OCR_FALLBACK_PROMPT.strip()
        if fallback_prompt:
            lines = parse_transcription(
                await self._transcribe_page(page_number, png, prompt=fallback_prompt)
            )
            if _has_text(lines):
                return lines

        # An inked page that produced no text under any prompt must never be
        # passed off as an empty page — that would silently drop its content
        # (and any PII on it) from the "anonymized" result.
        raise VisionOCRError(
            f"OCR produced no text for page {page_number}, which is not blank. "
            "The document was not processed to avoid silently dropping a page.",
            status_code=422,
        )

    def _render_pages(self, data: bytes) -> list[tuple[bytes, bool]]:
        """Render each page to PNG, paired with whether it carries meaningful
        ink (used to tell a genuinely blank page from one OCR dropped)."""
        import pypdfium2 as pdfium

        try:
            document = pdfium.PdfDocument(data)
        except Exception as exc:
            raise VisionOCRError(
                "The PDF could not be rendered for OCR (malformed?).", status_code=415
            ) from exc
        try:
            pages: list[tuple[bytes, bool]] = []
            for page in document:
                bitmap = page.render(scale=self._settings.VISION_OCR_RENDER_SCALE)
                pil_image = bitmap.to_pil()
                buffer = io.BytesIO()
                pil_image.save(buffer, format="PNG")
                pages.append((buffer.getvalue(), _page_has_ink(pil_image)))
                page.close()
            return pages
        finally:
            document.close()

    async def _transcribe_page(
        self, page_number: int, png: bytes, prompt: str | None = None
    ) -> str:
        settings = self._settings
        timeout = settings.VISION_OCR_TIMEOUT_SECONDS
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        kwargs: dict = {
            "model": settings.VISION_OCR_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt or settings.VISION_OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": settings.VISION_OCR_MAX_TOKENS,
            "temperature": 0.0,
        }
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body

        try:
            async with openai.AsyncOpenAI(
                api_key=settings.VISION_OCR_API_KEY or "EMPTY",
                base_url=settings.VISION_OCR_API_BASE,
                timeout=timeout,
                max_retries=1,
                http_client=httpx.AsyncClient(follow_redirects=False, timeout=timeout),
            ) as client:
                response = await client.chat.completions.create(**kwargs)
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise VisionOCRError(
                f"The vision OCR endpoint is unreachable (page {page_number})."
            ) from exc
        except openai.APIStatusError as exc:
            raise VisionOCRError(
                f"The vision OCR endpoint returned an error on page {page_number} "
                f"(HTTP {exc.status_code})."
            ) from exc

        content = response.choices[0].message.content if response.choices else None
        if content is None:
            raise VisionOCRError(
                f"The vision OCR endpoint returned no text for page {page_number}."
            )
        return content
