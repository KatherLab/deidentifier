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
difficult scans, and it returns bounding boxes — which is what makes the
reconstructed redacted PDF possible.

```env
OCR_ENGINE=llm_vision
VISION_OCR_API_BASE=http://unlimited-ocr:8000/v1
VISION_OCR_API_KEY=
VISION_OCR_MODEL=baidu/Unlimited-OCR
VISION_OCR_DIALECT=unlimited_ocr
```

### Dialects

`VISION_OCR_DIALECT` selects the model family's *dialect*: the prompt and
request settings the model expects, and the parser for its response format.
An unknown dialect name fails the request rather than guessing — a mis-parsed
response would silently drop text.

| `VISION_OCR_DIALECT` | Model family | Response format | Boxes |
|---|---|---|---|
| `unlimited_ocr` (default) | `baidu/Unlimited-OCR` on vLLM | layout lines (`text [x1, y1, x2, y2]…`) | per line |
| `chandra` | datalab chandra (e.g. `chandra-ocr-2`) on vLLM | structured HTML blocks with `data-bbox` | per block |
| `plain` | any generic vision model | plain text / Markdown | none — scanned-PDF export falls back to full-page rasterization |

A dialect only supplies defaults. Setting any of the variables below overrides
it; leaving them unset uses the dialect's recipe.

| Variable | Unset means | Notes |
|---|---|---|
| `VISION_OCR_PROMPT` | dialect default | Prompt sent with each page image. |
| `VISION_OCR_FALLBACK_PROMPT` | dialect default | Retry prompt for a page transcribed to (near-)empty text while the rendered page clearly has ink. Explicitly empty (`VISION_OCR_FALLBACK_PROMPT=`) disables the fallback. |
| `VISION_OCR_MAX_TOKENS` | dialect default (8192; chandra 12384) | Per page. |
| `VISION_OCR_EXTRA_BODY` | dialect default | Raw JSON merged into each request body (e.g. vLLM's `vllm_xargs`); `{}` sends none. |
| `VISION_OCR_TIMEOUT_SECONDS` | `600` | Per page. |
| `VISION_OCR_MAX_CONCURRENT_PAGES` | `2` | **Total** page requests in flight across all documents. |
| `VISION_OCR_RENDER_SCALE` | `2.8` | 1.0 = 72 dpi, 2.8 ≈ 200 dpi. Higher is slower and not always better. |

> **Upgrading from ≤ 0.1.3:** the `unlimited_ocr` dialect now sends the
> documented Unlimited-OCR `VISION_OCR_EXTRA_BODY` recipe by default. If your
> `llm_vision` endpoint serves a *different* model and rejects those vLLM
> parameters, set `VISION_OCR_DIALECT=plain` (or `chandra`) — or pin
> `VISION_OCR_EXTRA_BODY={}`.

### Several models at once: profiles

`VISION_OCR_PROFILES` configures several selectable OCR models side by side —
useful for comparing models on real documents, or offering a specialist model
(handwriting, say) next to the everyday one:

```env
VISION_OCR_API_BASE=http://localhost:8100/v1
VISION_OCR_PROFILES=[{"name":"Chandra","model":"chandra-ocr-2","dialect":"chandra"},{"name":"Unlimited","model":"baidu/Unlimited-OCR","dialect":"unlimited_ocr"}]
```

(No spaces inside the JSON — some `.env` parsers and IDE inspections only
allow spaces in quoted values.)

Each entry needs `name` and `model`; `dialect`, `api_base`, `api_key`,
`prompt`, `fallback_prompt`, `max_tokens` and `extra_body` are optional and
inherit the flat `VISION_OCR_*` values — two models behind one endpoint are
just name + model + dialect. The **first entry is the default**; when at least
two are configured, the advanced settings show an *OCR model* picker and the
choice is captured per document. A selected profile that does not exist fails
the request — it is never silently swapped for the default.

Profiles are a deployment decision like every other endpoint: `/api/v1/status`
lists each profile's host, and the header warns when any of them is not local
— every profile is a place a document can be sent to, whether or not it is the
default. There is **no automatic fallback** between profiles; a failing model
fails the document loudly rather than silently re-routing it to another one.

Pages are rendered with `pypdfium2` (permissively licensed, deliberately not
AGPL `pymupdf`). **The engine fails closed**: if any page cannot be
transcribed, the whole document fails rather than producing a partial
transcript that would look complete.

### The Unlimited-OCR sidecar

`compose.unlimited-ocr.yml` runs `baidu/Unlimited-OCR` on the stock
`vllm/vllm-openai` image — the model is supported by upstream vLLM since
v0.25.0 — and wires it up automatically (NVIDIA GPU + Container Toolkit
required):

```bash
docker compose -f compose.yml -f compose.unlimited-ocr.yml up -d
```

Standalone, outside compose — note the port: vLLM's default 8000 collides with
the backend.

```bash
docker run --rm --gpus all --network host --ipc host \
  vllm/vllm-openai:latest baidu/Unlimited-OCR \
  --port 8100 --trust-remote-code \
  --logits_processors vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor \
  --no-enable-prefix-caching --mm-processor-cache-gb 0
```

```env
VISION_OCR_API_BASE=http://localhost:8100/v1
VISION_OCR_MODEL=baidu/Unlimited-OCR
VISION_OCR_DIALECT=unlimited_ocr
```

### chandra

[datalab chandra](https://github.com/datalab-to/chandra) models return
structured HTML per page; the `chandra` dialect prompts for it and parses it
back into text lines and block-level bounding boxes — no chandra client
library involved.

`compose.chandra.yml` runs it as a GPU sidecar on the stock
`vllm/vllm-openai` image and wires it up automatically, exactly like the
Unlimited-OCR overlay (NVIDIA GPU + Container Toolkit required):

```bash
docker compose -f compose.yml -f compose.chandra.yml up -d
```

Or against your own vLLM serving it:

```env
VISION_OCR_API_BASE=http://localhost:8100/v1
VISION_OCR_MODEL=chandra-ocr-2
VISION_OCR_DIALECT=chandra
```

chandra boxes whole blocks rather than lines; a multi-line block's box is
subdivided into equal vertical strips for the reconstructed PDF. Placement
within a block is therefore approximate — coarser than Unlimited-OCR's
per-line boxes, but text and redaction boxes stay consistent with each other.

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
