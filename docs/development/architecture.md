# Architecture

The deep reference is
[`AGENTS.md`](https://github.com/KatherLab/deidentifier/blob/main/AGENTS.md) in
the repository root. This page is the orientation layer.

## Shape

Two containers, no state:

```text
Browser ── nginx (SPA + /api proxy) ── FastAPI ── LLM / OCR endpoints
                                          └───── in-memory cache
```

Deliberately absent: database, migrations, task queue, object storage,
authentication, WebSockets. The app is a stateless transformer of a document
into an anonymized document.

Conventions come from the sibling project
[llmaixweb](https://github.com/KatherLab/llmaixweb) — layout, config pattern,
service style, frontend primitives — minus those layers.

## The pipeline

```text
extraction → detection → resolution → transformation → validation
```

| Stage | Module | Responsibility |
|---|---|---|
| Extraction | `utils/extraction.py` | Format routing; PDF text probe; OCR dispatch. Returns text, source type, page ranges, layout lines, warnings. |
| Detection | `utils/rules.py`, `utils/llm_detection.py`, `utils/grounding.py` | Propose spans. The LLM returns strings; grounding turns them into verified offsets. |
| Resolution | `utils/resolver.py` | Merge duplicates, resolve overlaps. Exactly one transformation per character. |
| Transformation | `utils/transformation.py`, `utils/policy.py` | Pure functions applied right-to-left on a copy of the source. |
| Validation | `utils/leakage.py` | Re-scan the output; produce warnings and a status. Never edits. |

`utils/pipeline.py` orchestrates all five and is the only entry point the
routers use.

## The three invariants

**1. The source text is never modified.** Detectors propose spans; only
`apply_policy()` produces new text, and it does so on a copy. The review UI
highlights the original.

**2. Every span is verified against the source.** `validate_spans()` rejects
any span whose `text[start:end]` does not match, for every detector including
the LLM. Offsets are Unicode code points throughout; the frontend converts via
`Array.from()`.

**3. Failure is loud.** A detector that cannot run raises `DetectorError` and
the request fails. An export that cannot be verified is refused. Validation
downgrades the status rather than silently fixing the output.

## Why the LLM never returns offsets

Language models are unreliable at character arithmetic. So the model returns
mention *strings*, and `utils/grounding.py` locates them deterministically —
exact match first, then umlaut variants, de-hyphenation, and whitespace
normalization; all occurrences of the same string get the same type; anything
that cannot be located becomes a warning.

This is what makes prompt injection a bounded problem: the model's influence
ends at "which strings are identifiers". It never writes output text, never
picks an endpoint, and never changes a code path.

## Concurrency

Requests are `async` end to end. Two process-wide semaphores
(`utils/concurrency.py`) bound the expensive work globally, not per request:
`LLM_MAX_CONCURRENT_REQUESTS` over passes × chunks × documents, and
`VISION_OCR_MAX_CONCURRENT_PAGES` over OCR pages. The frontend streams up to
five documents at once; the backend interleaves their stage work under those
caps.

## The cache

`utils/cache.py` holds `request_id → CachedDetection` (text, resolved spans,
OCR layout, file hash) for 15 minutes, bounded at 100 entries, in process
memory. It exists so a correction in the review view re-runs only the cheap
deterministic stages, and so a PDF export can skip re-OCR when the re-sent
file's hash matches. Expiry surfaces as HTTP 410 and the frontend re-posts the
source. It is the only place document text lives between requests.

## Frontend

A single-view SPA — no router. `App.vue` switches between `InputPanel` and
`ResultView` on `session.phase`.

`stores/session.ts` is the heart and the only place document content lives. It
models a **batch**: one document per dropped file, each owning its own result,
corrections, previews, selection, and panel layout, each streaming its own
`/anonymize/stream` request. All actions apply to the active document.

Layers: components → `services/*Api.ts` → the shared axios instance. Components
never import the instance. Streaming goes through `services/anonymizeStream.ts`
(`fetch` + NDJSON, because axios cannot stream a response body in the browser).

## Where to start reading

| Question | File |
|---|---|
| How does a request flow end to end? | `backend/src/utils/pipeline.py` |
| What exactly is an entity? | `backend/src/schemas/entities.py` |
| How is the LLM prompted and parsed? | `backend/src/utils/llm_detection.py` |
| How do strings become offsets? | `backend/src/utils/grounding.py` |
| What does the frontend hold? | `frontend/stores/session.ts` |
| What is checked after the fact? | `backend/src/utils/leakage.py` |
