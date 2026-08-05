# OCR engines

Scanned PDFs are detected automatically: if the first
`PDF_MAX_PAGES_FOR_TEXT_PROBE` pages carry fewer than
`DOCLING_MIN_EXTRACTED_CHARS_PDF` extractable characters, the document is
routed to the configured `OCR_ENGINE`.

| `OCR_ENGINE` | Status | Needs |
|---|---|---|
| `none` (default) | Scanned PDFs are **rejected** with a clear message | — |
| `docling_tesseract` | Available | a docling-serve instance |
| `llm_vision` | Available | an OpenAI-compatible vision model (GPU) |
| `mistral_ocr` | **Not implemented** — returns 501 | — |

## Native PDFs

No OCR involved. With `DOCLING_SERVE_URL` set, extraction goes through
docling-serve (better layout handling); if it is unset or unreachable, the app
falls back to local `pypdf` extraction and says so in a warning. Either way the
app works with no services at all — that fallback is why the default install
needs nothing.

## `docling_tesseract`

```env
OCR_ENGINE=docling_tesseract
DOCLING_SERVE_URL=http://docling-serve:5001
```

CPU-only, fast, and adequate for clean scans of printed documents. Quality
drops sharply on skew, noise, poor contrast, and handwriting. `DOCLING_SERVE_URL`
is required; without it the request fails with 503 rather than silently
degrading.

## `llm_vision`

Renders each page to a PNG and has a vision model transcribe it. Much better on
difficult scans, and it returns line-level bounding boxes — which is what makes
the reconstructed redacted PDF possible.

```env
OCR_ENGINE=llm_vision
VISION_OCR_API_BASE=http://unlimited-ocr:8000/v1
VISION_OCR_API_KEY=
VISION_OCR_MODEL=baidu/Unlimited-OCR
```

| Variable | Default | Notes |
|---|---|---|
| `VISION_OCR_PROMPT` | `<image>document parsing.` | The Unlimited-OCR recipe; works for most vision OCR models. |
| `VISION_OCR_FALLBACK_PROMPT` | `<image>Free OCR.` | Retry prompt for a page transcribed to (near-)empty text while the rendered page clearly has ink. Empty disables the fallback. |
| `VISION_OCR_MAX_TOKENS` | `8192` | Per page. |
| `VISION_OCR_EXTRA_BODY` | — | Raw JSON merged into each request body (e.g. vLLM's `vllm_xargs`). |
| `VISION_OCR_TIMEOUT_SECONDS` | `600` | Per page. |
| `VISION_OCR_MAX_CONCURRENT_PAGES` | `2` | **Total** page requests in flight across all documents. |
| `VISION_OCR_RENDER_SCALE` | `2.8` | 1.0 = 72 dpi, 2.8 ≈ 200 dpi. Higher is slower and not always better. |

Pages are rendered with `pypdfium2` (permissively licensed, deliberately not
AGPL `pymupdf`). **The engine fails closed**: if any page cannot be
transcribed, the whole document fails rather than producing a partial
transcript that would look complete.

### The Unlimited-OCR sidecar

`compose.unlimited-ocr.yml` runs `baidu/Unlimited-OCR` on vLLM and wires it up
automatically (NVIDIA GPU + Container Toolkit required):

```bash
docker compose -f compose.yml -f compose.unlimited-ocr.yml up -d
```

Standalone, outside compose — note the port: vLLM's default 8000 collides with
the backend.

```bash
docker run --rm --gpus all --network host --ipc host \
  vllm/vllm-openai:unlimited-ocr baidu/Unlimited-OCR \
  --port 8100 --trust-remote-code \
  --logits_processors vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor \
  --no-enable-prefix-caching --mm-processor-cache-gb 0
```

```env
VISION_OCR_API_BASE=http://localhost:8100/v1
VISION_OCR_MODEL=baidu/Unlimited-OCR
VISION_OCR_EXTRA_BODY={"skip_special_tokens": false, "vllm_xargs": {"ngram_size": 35, "window_size": 128}}
```

## OCR quality is a privacy control

Bad OCR is not just an inconvenience: **a garbled name is a name no detector
can find**, and the document will still be reported as processed. Two
mitigations are built in — every OCR result carries a warning that recognition
errors are possible, and the LLM audit is asked to flag garbled passages as an
`ocr_quality` concern — but neither replaces looking at the source panel.

When a document comes back with implausibly little or visibly broken text,
treat the result as unusable rather than clean.

## Forcing OCR

A PDF that *has* a text layer skips OCR entirely — a problem when that layer is
garbage (a bad scan pipeline, or a mixed document). Users can switch on **OCR
erzwingen** in the advanced settings to re-OCR every page. The option only
appears when an OCR engine is configured.

## Troubleshooting

| Symptom | Cause |
|---|---|
| *This PDF appears to contain scanned images and no extractable text.* | `OCR_ENGINE=none`. |
| *OCR engine 'docling_tesseract' requires DOCLING_SERVE_URL* | Engine selected without its service. |
| *OCR produced no text for this document.* | Empty transcription. Fails deliberately — an empty document must never be reported as anonymized. |
| *OCR engine 'mistral_ocr' is not available yet* | Not implemented; pick another engine. |
| Very slow | Lower `VISION_OCR_RENDER_SCALE`, or raise `VISION_OCR_MAX_CONCURRENT_PAGES` if the GPU has headroom. |
