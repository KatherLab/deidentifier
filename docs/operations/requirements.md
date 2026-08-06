# Requirements & sizing

## The app itself

The backend is I/O-bound: it waits on the LLM and OCR endpoints and does very
little compute of its own. Nothing is persisted, so there is no storage to
size.

| | Minimum | Comfortable |
|---|---|---|
| CPU | 2 cores | 4 cores |
| RAM | 2 GB | 4 GB |
| Disk | ~2 GB for the images | — |
| GPU | none | only for a co-located OCR/LLM sidecar |

RAM scales with concurrent documents, not with corpus size. The dominant
consumers are the rendered page images of a scanned PDF during OCR and the
detection cache (bounded at 100 entries; 15 minutes, extendable up to the
configured ceiling).

Supported platforms: Linux with Docker or Podman. macOS works for development.

## What you actually need to size

The models, not the app:

- **Detection LLM** — an OpenAI-compatible endpoint. Throughput here sets your
  throughput: a document is split into chunks, and every chunk runs
  `LLM_DETECTION_PASSES` times (default 2), plus one re-check call per
  document. `LLM_MAX_CONCURRENT_REQUESTS` (default 4) caps the total in flight
  across all documents.
- **OCR** — only if you process scans. A vision-LLM engine needs a GPU;
  docling-serve with Tesseract runs on CPU. `VISION_OCR_MAX_CONCURRENT_PAGES`
  (default 2) caps page requests globally.

See [LLM endpoints](llm-endpoints.md) and [OCR engines](ocr-engines.md).

## Network

- Users → `frontend` (port 8080 by default), behind your own auth proxy.
- `backend` → the configured LLM/OCR endpoints. Nothing else.
- No outbound internet access is required at runtime. There is no telemetry, no
  CDN, and no third-party font or script.

The backend container publishes no port at all: nginx in the `frontend`
container proxies `/api/` to it over the compose network.

## Browsers

Any current Chromium, Firefox, or Safari. The redacted-PDF preview uses the
browser's built-in PDF viewer; where that is unavailable the download still
works.

## Before you process real data

Technical requirements are the easy part. Also settle:

- Who the data controller is and which legal basis applies
  ([DPIA template](../DPIA_TEMPLATE.md)).
- Where document content is allowed to flow ([Data flow](../DATA_FLOW.md)).
- Who reviews the output, and against what standard
  ([Security overview](../SECURITY.md)).
- How well the pipeline performs on **your** document types
  ([Evaluation](../evaluation/index.md)).
