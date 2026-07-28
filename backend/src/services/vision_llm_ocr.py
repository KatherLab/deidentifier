"""Vision-LLM OCR via any OpenAI-compatible endpoint (adapted from llmaixweb).

Designed for and tested with baidu/Unlimited-OCR served by vLLM, but works
with any vision model that transcribes page images: PDF pages are rendered to
PNG with pypdfium2, sent per page (concurrently, order preserved) as data
URLs, and the transcriptions are joined.

Fail-closed: if any single page fails, the whole document fails — a document
missing a page must never be reported as anonymized.
"""

import asyncio
import base64
import io
import json
import re

import httpx
import openai

from ..core.config import Settings


class VisionOCRError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


# Model markup such as <|ref|>…<|/ref|> emitted with skip_special_tokens=false.
_SPECIAL_TOKENS = re.compile(r"<\|[^|>]{0,40}\|>")


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

    async def process_pdf(self, data: bytes) -> list[str]:
        """Return one transcription per page, in order."""
        images = self._render_pages(data)
        if not images:
            raise VisionOCRError("The PDF contains no pages.", status_code=422)
        semaphore = asyncio.Semaphore(self._settings.VISION_OCR_MAX_CONCURRENT_PAGES)

        async def limited(page_number: int, png: bytes) -> str:
            async with semaphore:
                return await self._transcribe_page(page_number, png)

        return list(
            await asyncio.gather(
                *(limited(number, png) for number, png in enumerate(images, start=1))
            )
        )

    def _render_pages(self, data: bytes) -> list[bytes]:
        import pypdfium2 as pdfium

        try:
            document = pdfium.PdfDocument(data)
        except Exception as exc:
            raise VisionOCRError(
                "The PDF could not be rendered for OCR (malformed?).", status_code=415
            ) from exc
        try:
            images: list[bytes] = []
            for page in document:
                bitmap = page.render(scale=self._settings.VISION_OCR_RENDER_SCALE)
                pil_image = bitmap.to_pil()
                buffer = io.BytesIO()
                pil_image.save(buffer, format="PNG")
                images.append(buffer.getvalue())
                page.close()
            return images
        finally:
            document.close()

    async def _transcribe_page(self, page_number: int, png: bytes) -> str:
        settings = self._settings
        timeout = settings.VISION_OCR_TIMEOUT_SECONDS
        data_url = "data:image/png;base64," + base64.b64encode(png).decode()
        kwargs: dict = {
            "model": settings.VISION_OCR_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": settings.VISION_OCR_PROMPT},
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
        return _SPECIAL_TOKENS.sub("", content).strip()
