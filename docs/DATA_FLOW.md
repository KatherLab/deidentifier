# Data flow

Where document content goes, and where it does not.

## The full path

```text
Browser ──(1)── nginx ──(2)── backend ──(3)── LLM endpoint
                                 │
                                 └──(4)── OCR endpoint (scanned PDFs only)
                                 │
                                 └──(5)── in-memory cache (15 min, ≤12 h)
```

| # | Hop | Content | Notes |
|---|---|---|---|
| 1 | Browser → frontend | The document (multipart or JSON) | Over your TLS-terminating proxy. |
| 2 | nginx → backend | The same request | Internal to the compose network; the backend publishes no port. nginx may spool a large body or response through `/tmp`, which is a `tmpfs` — see [Data retention](DATA_RETENTION.md). |
| 3 | Backend → LLM | Document text, in chunks; then the anonymized output for the re-check | Only when `llm` is enabled. `OPENAI_API_BASE`. |
| 4 | Backend → OCR | Rendered page images | Only for scanned PDFs, only when an OCR engine is configured. |
| 5 | Backend → memory | Extracted text + detected spans, keyed by request id | 15 min, extendable by the reviewer up to 12 h (configurable); max 100 entries, process memory only. |
| ← | Backend → browser | Source text, anonymized text, entities, warnings | `Cache-Control: no-store`. |

Content flows nowhere else. There is no database, no object storage, no volume,
no telemetry endpoint, no CDN, and no analytics.

## Per endpoint

| Endpoint | Receives | Returns | Leaves the backend? |
|---|---|---|---|
| `POST /api/v1/anonymize` | Document or pasted text; or a request id + overrides | Source text, anonymized text, entities, validation, timings | To the LLM (detection + re-check) and, for scans, to OCR |
| `POST /api/v1/anonymize/stream` | Same | Same, as NDJSON with progress events | Same |
| `POST /api/v1/export/pdf` | The original PDF (re-sent) + overrides | The redacted PDF | Only on a cache miss (re-runs extraction/detection) |
| `POST /api/v1/export/pdf/pages` | The original PDF (re-sent) | Page PNGs + image boxes | No |
| `POST /api/v1/anonymize/{id}/extend` | A request id | Remaining seconds + whether more is possible | No — it only postpones the cache eviction |
| `DELETE /api/v1/anonymize/{id}` | A request id | Nothing (204 either way) | No — it only forgets the cached detection |
| `GET /api/v1/status` | — | Detector states, OCR engine, endpoint **hosts** + locality, limits | No |
| `GET /health/live`, `/health/ready` | — | Status only | Readiness may probe configured endpoints |

`/api/v1/status` returns hosts, never full URLs, keys, or filesystem paths. It
is what the UI uses to warn that content will leave the machine, so it has to
stay safe to expose.

## In the browser

| Stored | Where | Why |
|---|---|---|
| Document text, results, corrections | Pinia store — **memory only** | Cleared on reload. Never `localStorage`/`sessionStorage`. |
| Object URLs for previews (original PDF, redacted PDF, rendered pages) | Memory, revoked on reset | Needed to display a PDF. |
| `darkMode`, `expertMode`, `keepFilenames` | `localStorage` | UI preferences only. |

That split is a hard rule in the codebase: nothing derived from a document is
ever persisted client-side.

## What is logged

Per request: a short hash of the request id (`ref=`), source type, character
count, entity count, validation status, timings; for exports also the byte size
and the number of redaction areas.

Never logged: document text, extracted text, anonymized text, entity text,
prompts, filenames — and the **request id itself**, which is a capability: for
as long as the cache entry lives, whoever holds it can ask the API for the
document. The `ref=` hash is there so log lines about one request can still be
correlated. A structured logger drops all these field names before the line
is written and records `rejected_fields=…` instead. The escape hatch
(`APP_ALLOW_INSECURE_CONTENT_LOGGING`) prints a loud warning at startup and is
refused in production mode.

## Retention at each stop

| Stop | Retention |
|---|---|
| Browser memory | Until reload or **Neues Dokument** |
| Browser `localStorage` | UI preferences only, indefinitely |
| Backend memory (request) | The request |
| Backend cache | 15 minutes from creation, extendable by the reviewer in 1 h steps up to 12 h (all configurable), or until the UI drops it, eviction (100 entries), or restart |
| Backend disk | **Nothing.** Read-only filesystem, `tmpfs` for `/tmp`, no volumes |
| Frontend (nginx) disk | **Nothing.** Spooled bodies/responses go to `/tmp`, mounted as a `tmpfs`, and are deleted when the request ends |
| Backend logs | Metadata only, per your log retention |
| LLM / OCR endpoint | **Whatever that service does** — see below |

## The one you have to answer yourself

The app's retention story ends at hop 3 and 4. Whether your model endpoint logs
prompts, caches them, or trains on them is a property of *that* service, not of
this one.

Before processing real data, establish for every configured endpoint: who
operates it, whether it logs request bodies, what its retention is, and whether
it is inside your organizational boundary. A hosted API is a data transfer to a
processor and needs the corresponding agreement. See the
[DPIA template](DPIA_TEMPLATE.md).
