# Data retention

The short version: **the application stores nothing.** This page is mostly a
list of the places where that claim needs a footnote.

## Server side

| Store | What | Retention | Notes |
|---|---|---|---|
| Database | — | — | There is none. |
| Object storage / volumes | — | — | The backend runs read-only with no volumes. |
| Temporary files | — | — | Extraction and OCR work in memory; `/tmp` is a `tmpfs` in **both** containers — see the note below. |
| Request memory | Document text, spans, output | Duration of the request | Freed when the response completes. |
| Detection cache | Extracted text, resolved spans, OCR layout, file hash | **15 min, extendable by the reviewer in 1 h steps, never past 12 h** — all three configurable | Process memory only. Gone on restart. Max 100 entries, oldest evicted first. |
| Logs | Metadata only (counts, timings, status, a hashed request reference) | Your log retention | Contains no document content and no request id by design — [Data flow](DATA_FLOW.md). |

### Why the frontend needs a `tmpfs` too

nginx spools a request body larger than `client_body_buffer_size` — and a
proxied response larger than its buffers — to a temporary file. Both carry
document content. The frontend container therefore mounts `/tmp` as a `tmpfs`
(`compose.yml`), and `nginx.conf` raises the body buffer to 1 MB and turns
response buffering off for `/api/`, so the ordinary case never spools at all
and the exceptional one lands in RAM. Without the `tmpfs` those files are
written to the container's writable layer, i.e. to a disk, where the freed
blocks outlive the request. **If you deploy the frontend image outside this
compose file, mount a `tmpfs` at `/tmp` yourself.**

### Why the cache exists

Without it, every correction in the review view would re-run LLM detection on
the whole document — slow, expensive, and a fresh copy of the text sent to the
model each time. The cache is the *privacy-cheaper* option: it keeps one copy
in memory for a bounded time so corrections need no further model calls.

Its two honest caveats: the text sits in process memory while the window runs,
and the memory is not explicitly zeroed on eviction (Python's allocator
decides). A backend restart clears everything.

The 15 minutes are counted from when the entry was **created**. Reading it —
every correction, every PDF preview — does not extend that window, so no
review session can silently keep a document resident. A background task sweeps
expired entries once a minute, so an idle server does not hold the last
documents it saw until the next request arrives, and shutdown clears the cache
outright.

The review UI also gives up its entry early: closing a document, pressing
**Neues Dokument**, or closing the tab sends `DELETE /api/v1/anonymize/{id}`,
so in normal use the server-side copy ends when the user is done with it rather
than fifteen minutes later.

### The countdown and the extension

The top bar shows how much of that window is left and doubles as the
**Verlängern** button; the result view repeats the offer in a warning once the
time runs low. Extending is deliberately an *explicit act by the reviewer*, not
something a click anywhere in the app does as a side effect:

- one extension moves the deadline to **an hour from the moment it is pressed**,
  and can be taken at any time — a reviewer leaving their desk tops it up on the
  way out instead of losing the result while they are gone;
- it is repeatable, so a long review never becomes a race against a countdown;
- no entry survives longer than **12 hours after it was created**, however often
  it is extended — `POST /api/v1/anonymize/{id}/extend` then answers with
  `can_extend: false` and the UI says so instead of offering a dead button;
- the button extends every document of the current batch, since their windows
  run together.

The defaults suit a **research prototype** — long enough that the tool is
pleasant to use. Every bound is operator-configurable
(`RESULT_CACHE_TTL_MINUTES`, `RESULT_CACHE_EXTENSION_MINUTES`,
`RESULT_CACHE_MAX_LIFETIME_MINUTES`, `RESULT_CACHE_MAX_ENTRIES`), including a
one-line way to switch extending off entirely — see
[Tightening it](operations/configuration.md#tightening-it). What is *not*
configurable is the relationship between them: a read never extends anything,
and nothing outlives the ceiling.

That ceiling is what keeps the retention statement above true, so it is the one
number to agree on before deployment. The honest sentence for a DPIA is *"a
document stays in server memory while a reviewer is working on it, at most
`RESULT_CACHE_MAX_LIFETIME_MINUTES` (12 hours by default), and only in RAM"* —
not *"as long as a tab is open"*. Shorten it to whatever your governance
prefers; a shift length is a reasonable anchor.

When an entry expires the API answers 410 and the frontend re-sends the source
text from the browser. Users see *"Ergebnis abgelaufen – wird neu berechnet"*.

### The request id is a capability

While an entry lives, its `request_id` is the only thing needed to fetch the
document back from `POST /api/v1/anonymize`. Treat it like a credential: it
stays in the submitting browser, it is deliberately absent from the backend's
logs (which carry a short hash instead), and it should not be copied into
tickets or screenshots.

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
