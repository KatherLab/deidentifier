# Data retention

The short version: **the application stores nothing.** This page is mostly a
list of the places where that claim needs a footnote.

## Server side

| Store | What | Retention | Notes |
|---|---|---|---|
| Database | — | — | There is none. |
| Object storage / volumes | — | — | The backend runs read-only with no volumes. |
| Temporary files | — | — | Extraction and OCR work in memory; `/tmp` is a `tmpfs`. |
| Request memory | Document text, spans, output | Duration of the request | Freed when the response completes. |
| Detection cache | Extracted text, resolved spans, OCR layout, file hash | **≤15 minutes**, max 100 entries, evicted LRU-style | Process memory only. Gone on restart. |
| Logs | Metadata only (ids, counts, timings, status) | Your log retention | Contains no document content by design — [Data flow](DATA_FLOW.md). |

### Why the cache exists

Without it, every correction in the review view would re-run LLM detection on
the whole document — slow, expensive, and a fresh copy of the text sent to the
model each time. The cache is the *privacy-cheaper* option: it keeps one copy
in memory for a bounded time so corrections need no further model calls.

Its two honest caveats: the text sits in process memory for up to 15 minutes,
and the memory is not explicitly zeroed on eviction (Python's allocator
decides). A backend restart clears everything.

When an entry expires the API answers 410 and the frontend re-sends the source
text from the browser. Users see *"Ergebnis abgelaufen – wird neu berechnet"*.

## Client side

| Store | What | Retention |
|---|---|---|
| Pinia store (memory) | Documents, results, corrections, previews | Until reload or **Neues Dokument** |
| Object URLs | PDF previews, rendered pages | Revoked on reset |
| `localStorage` | `darkMode`, `expertMode`, `keepFilenames` | Indefinite — UI preferences only |

**No document content is ever written to `localStorage` or `sessionStorage`.**
That is enforced as a codebase rule, not a convention.

Downloads are a different matter: once a user exports a `.txt`, `.pdf`, or
`.zip`, retention of that file is governed by your endpoint policy, not by this
application.

## External endpoints

The pipeline sends document text to the configured LLM endpoint and page
images to the configured OCR endpoint. **Their retention is their own.**
Establish, per endpoint: request-body logging, cache duration, training use,
and organizational boundary. Record the answers in your
[DPIA](DPIA_TEMPLATE.md).

## Evaluation data

The evaluation harness is separate from the app and *does* write files:

- The report at `--output` — by default counts, offsets, and types, with **no
  literal entity text**, so it is safe to archive and share.
- With `--include-sensitive-text`, the report contains the literal text of
  missed entities. Treat it as identifiable data: never commit it, never attach
  it to an issue.
- Your annotated corpus is full document text with identifiers marked. It is
  patient data and needs patient-data handling.

## Deletion requests

There is nothing to delete on the server: no document, no result, and no
identifier is retained beyond the cache window. The relevant retention lives in
the *source* systems the documents came from and in whatever the user saved
from an export. Say exactly this when answering an information-governance
question, and point at the cache row above for completeness.
