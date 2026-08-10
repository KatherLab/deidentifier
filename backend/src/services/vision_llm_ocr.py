"""Vision-LLM OCR via any OpenAI-compatible endpoint (adapted from llmaixweb).

PDF pages are rendered to PNG with pypdfium2, sent per page (concurrently,
order preserved) as data URLs, and the transcriptions are joined. What the
model is asked and how its response is read is a per-model *dialect*
(`services/ocr_dialects.py`, selected by VISION_OCR_DIALECT): Unlimited-OCR's
layout lines, chandra's structured HTML, or plain text. The pipeline around
the dialect — rendering, concurrency, blank-page detection, fail-closed
semantics — is shared and identical for every model.

Fail-closed: if any single page fails, the whole document fails — a document
missing a page must never be reported as anonymized. A page that the primary
prompt transcribes to no text while it clearly has ink is retried once with the
fallback prompt; if it is still empty, the document fails rather than silently
dropping the page.
"""

import asyncio
import base64
import io
import json

import httpx
import openai

from ..core.config import Settings
from ..utils.concurrency import global_semaphore
from .ocr_dialects import TranscribedLine, build_dialect

__all__ = ["TranscribedLine", "VisionOCRError", "VisionOCRService"]


class VisionOCRError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


# A rendered page whose dark-pixel fraction is below this is treated as blank:
# an empty transcription is then expected, not a dropped page.
_MIN_INK_FRACTION = 0.002


def _has_text(lines: list[TranscribedLine]) -> bool:
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


class VisionOCRService:
    def __init__(self, settings: Settings):
        if not (settings.VISION_OCR_API_BASE and settings.VISION_OCR_MODEL):
            raise VisionOCRError(
                "OCR engine 'llm_vision' requires VISION_OCR_API_BASE and VISION_OCR_MODEL.",
                status_code=503,
            )
        self._settings = settings
        try:
            self._dialect = build_dialect(settings.VISION_OCR_DIALECT)
        except ValueError as exc:
            raise VisionOCRError(str(exc), status_code=503) from exc

        # Explicit settings win; unset (None) falls back to the dialect's
        # recipe. An *empty* fallback prompt stays empty: it means "no retry".
        self._prompt = (
            settings.VISION_OCR_PROMPT
            if settings.VISION_OCR_PROMPT is not None
            else self._dialect.default_prompt
        )
        self._fallback_prompt = (
            settings.VISION_OCR_FALLBACK_PROMPT
            if settings.VISION_OCR_FALLBACK_PROMPT is not None
            else self._dialect.default_fallback_prompt
        )
        self._max_tokens = settings.VISION_OCR_MAX_TOKENS or self._dialect.default_max_tokens
        if settings.VISION_OCR_EXTRA_BODY is None or not settings.VISION_OCR_EXTRA_BODY.strip():
            self._extra_body: dict = dict(self._dialect.default_extra_body)
        else:
            try:
                self._extra_body = json.loads(settings.VISION_OCR_EXTRA_BODY)
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
        lines = self._dialect.parse(await self._transcribe_page(page_number, png))
        if _has_text(lines) or not has_ink:
            return lines

        fallback_prompt = self._fallback_prompt.strip()
        if fallback_prompt:
            lines = self._dialect.parse(
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
        parts = [
            {"type": "text", "text": prompt or self._prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        if self._dialect.image_first:
            parts.reverse()
        kwargs: dict = {
            "model": settings.VISION_OCR_MODEL,
            "messages": [{"role": "user", "content": parts}],
            "max_tokens": self._max_tokens,
            "temperature": 0.0,
        }
        if self._dialect.top_p is not None:
            kwargs["top_p"] = self._dialect.top_p
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
