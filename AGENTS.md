# AGENTS.md — Deidentifier Codebase Guide

This file explains the structure, concepts, and conventions of the **Medical
Document Anonymizer** repository to help AI agents (and humans) work with the
codebase effectively.

---

## What is this?

A locally deployable web app that anonymizes German clinical documents. The
default experience is one screen: drop a document (or paste text), press one
button, get anonymized text out — plus a review view showing exactly what was
redacted and why.

**This is an internal evaluation tool. Its output does not establish legal
anonymization.** Any user-facing text, docs page, or README section that could
be read as a guarantee must be corrected, not softened.

**Tech stack:** Vue 3 + Vite + TypeScript + TailwindCSS v4 (frontend), FastAPI
+ Pydantic v2 (backend), `uv` for Python, the `openai` SDK for every
OpenAI-compatible endpoint. **No database, no Celery/Redis, no S3, no auth, no
Alembic** — the app runs behind the hospital's own auth proxy and persists
nothing.

The sibling project **llmaixweb** (https://github.com/KatherLab/llmaixweb) is
the convention source: layout, config pattern, service style, frontend
primitives. When a question is "how do we usually do this?", the answer is
usually "the way llmaixweb does it, minus the DB/queue/auth layers". A
reference clone may sit at `./llmaixweb`; it is gitignored and not part of
this repository.

---

## The five principles

Everything below follows from these. When a change conflicts with one of them,
the change is wrong.

1. **Immutable source, spans only.** No generative model ever rewrites a
   document. Detectors — including LLMs — only *propose* entities;
   deterministic code applies every edit via character offsets on the
   unchanged source text.
2. **Recall over precision.** A missed name is worse than an over-redacted
   word. Defaults over-redact; preservation is opt-in per entity in the review
   UI.
3. **Simple mode is the app, not a mode.** One sensible default policy on the
   main screen. Adjustments happen *after* processing, as per-entity overrides
   in the review view.
4. **Configurable endpoints, local by default.** All model/OCR backends are
   admin-configured base URLs. The UI shows a banner when a configured
   endpoint is not local, so users know where document content flows.
5. **Never claim more than was checked.** A detector that is enabled but
   cannot run fails the request (`DetectorError`) instead of silently
   producing a thinner result. Validation warnings downgrade the status; they
   never quietly edit the output.

---

## Top-level directory layout

```
deidentifier/
├── AGENTS.md                  # this file — the canonical dev/agent guide
├── CLAUDE.md                  # stub that @-includes AGENTS.md
├── README.md                  # short landing page → links into docs/
├── DESIGN_DOCUMENT.md         # the v1 design + milestones (why, not how)
├── CHANGELOG.md               # Keep a Changelog format
├── CITATION.cff               # academic citation metadata
├── THIRD_PARTY_NOTICES.md     # bundled OSS components + licenses
├── .env.example               # documents every variable (the config reference)
├── backend/
│   ├── .env.e2e               # fixture-only config for the Playwright harness
│   ├── tests/                 # pytest: unit/, integration/, files/ (fixtures)
│   └── src/
│       ├── main.py            # module-level `app = FastAPI(...)`, lifespan, wiring
│       ├── core/config.py     # Settings(BaseSettings), ENV_PATH pattern
│       ├── middleware/        # security_headers, error_handlers
│       ├── routers/v1/        # api.py + endpoints/ (anonymize, export, status, health)
│       ├── schemas/           # entities.py, anonymize.py (Pydantic contracts)
│       ├── services/          # external integrations only
│       ├── utils/             # the anonymization domain logic
│       └── evaluation/        # standalone scoring harness (not part of the app)
├── frontend/                  # llmaixweb layout: sources directly under frontend/
│   ├── App.vue, main.ts, index.html, vite.config.ts
│   ├── components/            # common/ (primitives) + anonymizer/ (the product)
│   ├── composables/, stores/, services/, types/, utils/
│   └── nginx.conf, docker-entrypoint.d/
├── e2e/                       # Playwright: tests/ (smoke) + screenshots/ (docs)
├── docs/                      # MkDocs source (see "Documentation site")
├── mkdocs.yml
├── .github/workflows/         # CI — currently workflow_dispatch only, see below
├── compose.yml                # backend + frontend
├── compose.dev.yml            # source mount + hot reload
├── compose.unlimited-ocr.yml  # GPU sidecar serving baidu/Unlimited-OCR via vLLM
├── Dockerfile.backend, Dockerfile.frontend
├── pyproject.toml, uv.lock, pytest.ini
├── package.json, vitest.config.ts, playwright*.config.ts
└── llmaixweb/                 # reference clone only — gitignored, never shipped
```

Deliberately **absent** (and not to be reintroduced without a design change):
`models/`, `db/`, `alembic/`, `celery/`, dynamic settings, auth/SSO, S3,
WebSockets, i18n.

---

## The pipeline

```text
Document (PDF / DOCX / TXT / pasted text)
  → extraction        utils/extraction.py     (probe → docling / OCR routing)
  → detection         utils/rules.py, utils/llm_detection.py (+ grounding.py)
  → resolution        utils/resolver.py       (merge + overlap resolution)
  → transformation    utils/transformation.py (deterministic, right-to-left)
  → validation        utils/leakage.py        (+ LLM re-check)
  → result + review UI
```

`utils/pipeline.py` orchestrates detect → resolve → transform → validate and is
the single entry point for both endpoints.

### 1. Extraction (`utils/extraction.py`)

- **TXT**: UTF-8 (+BOM), binary rejected. **DOCX**: paragraphs, tables,
  headers, footers via `python-docx`; warns on text boxes / comments / tracked
  changes.
- **PDF**: `services/pdf_text_probe.has_embedded_text(...)` decides scanned vs
  native (threshold `DOCLING_MIN_EXTRACTED_CHARS_PDF`, first
  `PDF_MAX_PAGES_FOR_TEXT_PROBE` pages).
  - Native → docling-serve `convert_pdf(do_ocr=False)` when `DOCLING_SERVE_URL`
    is set; on failure or when unset, **local pypdf extraction** — so the app
    works out of the box with no services at all.
  - Scanned (or `force_ocr=true`) → the configured `OCR_ENGINE`:
    `docling_tesseract`, `llm_vision` (implemented), `mistral_ocr` (501 — not
    yet), or `none` (scanned PDFs rejected with a clear message).
- Returns `ExtractedDocument(text, source_type, pages, layout, warnings)`.
  `source_type` is one of `paste | txt | docx | pdf | pdf-ocr` and drives the
  UI (a `pdf-ocr` result is a *reconstruction*, never the original pixels).
- **Never claim a scanned document was anonymized if no text was extracted** —
  empty OCR output raises `ExtractionError`.

### 2. Canonical entity schema (`schemas/entities.py`)

Every detector returns exactly this. 12 deliberately coarse types; sub-typing
(patient vs clinician, kind of ID) lives in `metadata`.

```python
class EntitySpan(BaseModel):
    start: int          # Unicode CODE POINT offset, inclusive
    end: int            # exclusive
    text: str
    entity_type: EntityType
    confidence: float
    detector: str
    metadata: dict[str, str | int | float | bool]
```

**Offsets are code points everywhere** — Python string indices. The frontend
converts via `Array.from(text)` (see `utils/textSegments.ts`) and never
recomputes offsets from modified text.

`validate_spans()` in `utils/detection.py` rejects any span whose
`text[start:end]` does not match the source, with a warning. That check runs on
*every* detector's output, including the LLM's.

### 3. Detection (`utils/detection.py` + friends)

`SpanDetector` protocol: `name`, `version`, `async detect(text) ->
DetectionOutcome`. `build_detectors(settings, ...)` instantiates the configured
list and **raises `DetectorError` for a detector that is enabled but cannot
run** (principle 5). Detectors:

| Detector | Module | Notes |
|---|---|---|
| `rules` | `utils/rules.py` | German regex/context recognizers with stable rule IDs (`de.email.v1`, …). Context-aware: a bare number is not an ID without a label. |
| `llm` | `utils/llm_detection.py` | The primary detector. Any OpenAI-compatible endpoint. |
| `mock` | `utils/detection.py` | Fixed fixture strings, tests/offline only. Production refuses to start with it. |
| `user_terms` | `utils/detection.py` | `TermListDetector` — the user's always-redact terms; word-bounded, case-insensitive, entirely independent of the model. Added implicitly when `redact_terms` are sent. |
| `privacy_filter` | — | Planned second net (Milestone 3); `detector_ready()` returns False. |

**The LLM returns strings, never offsets.** `utils/grounding.py` locates each
returned mention in the source deterministically (exact → umlaut variants →
de-hyphenated → whitespace-normalized), applies the same type to all
occurrences, and emits a warning for anything it cannot locate. Also relevant:
overlapping chunking (`LLM_CHUNK_CHARS` / `LLM_CHUNK_OVERLAP`), multi-pass
union (`LLM_DETECTION_PASSES`, later passes sample at a small temperature),
bisecting retry on truncated output, and prompt-injection hardening (the
document is fenced between `DOCUMENT START/END` markers and declared untrusted).

### 4. Resolution (`utils/resolver.py`)

Deterministic, before transformation. Exact duplicates merge (provenance in
`metadata.supporting_detectors`, confidence = max); identical offsets with
conflicting types → higher confidence wins; partial overlap → longer/earlier
span wins. Every conflict yields a `ResolutionDecision`. **One transformation
per character, always.**

### 5. Policy & transformation (`utils/policy.py`, `utils/transformation.py`)

One built-in `DEFAULT_POLICY` (recall-first): `PERSON_NAME → CONSISTENT_TAG`,
`OTHER_DATE → PRESERVE` (clinical timelines stay useful), everything else
`TYPE_MASK`. A request may send **only the deviations** as `policy`;
`merge_policy()` overlays them on the defaults. The frontend mirror lives in
`frontend/utils/policy.ts` and **must stay in sync** — there is a Vitest spec
asserting the key defaults.

Transformations are pure functions: `TYPE_MASK`, `CONSISTENT_TAG` (same
normalized string → same number), `GENERALIZE` (date → year), `REMOVE`
(`[GESCHWÄRZT]`), `PRESERVE`. Replacements are applied **right-to-left** so
earlier offsets stay valid.

Precedence in `apply_policy()`: explicit override (matched by
`(start, end, text)`) → `preserve_terms` → policy. An override that matches
nothing produces a warning rather than being dropped silently.

### 6. Leakage validation (`utils/leakage.py`)

A separate pass over the *output*:

1. Every non-preserved entity's original text must not remain.
2. Rule detectors re-run on the output.
3. Labelled fields (`Patient:`, `Name:`, `Anschrift:` …) followed by
   non-redacted content are flagged.
4. `LLM_RECHECK_ENABLED` (default on): the LLM audits the output
   (`recheck_output()`), producing **warnings only, never edits**. Full runs
   only — an override re-run carries an INFO note instead.

`compute_status()`: any HIGH → `FAIL`, any WARNING → `REVIEW_REQUIRED`, INFO
alone still `PASS`.

### 7. The request cache (`utils/cache.py`)

`request_cache` is an in-memory, TTL-bounded (15 min, 100 entries) map from
`request_id` to the detection result. It exists so review-UI overrides can
re-run the cheap deterministic stages without repeating LLM detection, and so
a PDF export can skip OCR when the re-sent file's SHA-256 matches.

**This is the only place document text lives between requests, and it lives in
process memory only.** An expired entry yields HTTP 410; the frontend
transparently re-posts the full source text.

---

## Backend architecture

### API surface

All under `/api/v1` (`routers/v1/api.py`), no auth:

| Route | Purpose |
|---|---|
| `POST /api/v1/anonymize` | Multipart (`file`) or JSON (`text`), dispatched by content type. JSON without `text` but with `request_id` + `overrides` is a **cheap re-run** from the cache. |
| `POST /api/v1/anonymize/stream` | Same inputs, streams NDJSON `{"event":"progress"…}` lines then `{"event":"result"…}`. Inputs are parsed *before* streaming starts, so malformed requests still fail with normal HTTP errors. A client disconnect cancels the pipeline. |
| `POST /api/v1/export/pdf` | Redacted-PDF export. The client **re-sends the original file** (nothing is stored); `request_id` + matching hash avoids re-running OCR/detection. |
| `POST /api/v1/export/pdf/pages` | Renders pages as PNGs for the area-redaction editor, with embedded-image boxes as one-click suggestions. |
| `GET /api/v1/status` | Configured detectors + OCR engine, endpoint **hosts** and their locality, limits. Never returns paths, keys, or full URLs. |
| `GET /health/live`, `GET /health/ready` | Liveness/readiness. |

Limits: `APP_MAX_UPLOAD_MB` (413 before buffering), `APP_MAX_TEXT_CHARS`,
extensions `.txt/.docx/.pdf`. `Cache-Control: no-store` on content routes
(`middleware/security_headers.py`).

### Key backend files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, lifespan (`validate_production_settings`), CORS, security headers, error handlers, router wiring. Docs/OpenAPI disabled when `APP_ENV=production`. |
| `core/config.py` | `Settings(BaseSettings)`, `ENV_PATH` → `.env` → `backend/.env`, `@lru_cache get_settings()`, `validate_production_settings()`. **No network checks at startup** — readiness is reported by `/health/ready`, not by refusing to boot. |
| `utils/pipeline.py` | `run_anonymization()` / `rerun_with_overrides()` — the orchestrator. |
| `utils/detection.py` | Detector protocol, registry, `MockDetector`, `TermListDetector`, `validate_spans`. |
| `utils/rules.py` | German recognizers (dates, phones, IBAN, postal codes, labelled IDs). |
| `utils/llm_detection.py` | Prompts, structured output, chunking, passes, retries, `recheck_output()`. |
| `utils/grounding.py` | LLM mention strings → validated source offsets. |
| `utils/resolver.py` | Merge + overlap resolution. |
| `utils/policy.py`, `utils/transformation.py` | Default policy, labels, pure transformations. |
| `utils/leakage.py` | Output validation + `compute_status`. |
| `utils/cache.py` | `request_cache` (TTL, bounded, in-memory). |
| `utils/pdf_export.py` | Native-PDF true redaction, rasterized fallback, scanned-PDF reconstruction, page rendering. **Fails closed**: an export that cannot be verified is refused. |
| `utils/safe_logging.py` | `get_safe_logger()` — the only logger application code may use. |
| `utils/concurrency.py` | Process-wide named semaphores (global LLM/OCR request budgets across concurrent documents). |
| `services/docling_serve_client.py` | docling-serve HTTP client. |
| `services/pdf_text_probe.py` | Embedded-text probe (pypdf). |
| `services/vision_llm_ocr.py` | Vision-LLM OCR: page rendering (pypdfium2), per-page concurrency, layout lines, empty-page fallback prompt. |
| `middleware/security_headers.py` | CSP, X-Frame-Options, Referrer-Policy, `no-store`. |
| `middleware/error_handlers.py` | Global handlers → safe messages (never raw upstream errors). |

### Safe logging

`FORBIDDEN_FIELDS` (`text`, `content`, `prompt`, `filename`, `entity_text`,
`anonymized_text`, `source_text`, `document`) are dropped and recorded as
`rejected_fields=…` unless `APP_ALLOW_INSECURE_CONTENT_LOGGING` is on (dev
only, loud startup warning, refused in production).

**Use `get_safe_logger(__name__)`, never `logging.getLogger(...)` directly, and
never f-string document content into a log message** — the filter works on
field names, so `logger.info("x", chars=len(text))` is right and
`logger.info(f"text: {text}")` defeats it.

### Configuration

`Settings` in `core/config.py`; `.env.example` is the reference and documents
every variable. `validate_production_settings()` refuses to start when
`APP_ENV=production` and: the mock detector is enabled, insecure content
logging is on, or `llm` is enabled without `OPENAI_API_BASE`/`LLM_MODEL`.

Adding a setting = field on `Settings` + a documented block in `.env.example`
+ (if user-visible) a row in `docs/operations/configuration.md`.

---

## Frontend architecture

A single-view SPA — there is no router. `App.vue` renders the header (system
hints, expert-mode popover, dark-mode toggle) and switches between
`InputPanel.vue` and `ResultView.vue` on `session.phase`.

### Stores (Pinia, `stores/`)

- **`session.ts`** — the heart, and **the only place document content and
  results live**. Multi-document model: every submit creates a *batch* (one
  document per dropped file; pasted text is a single-document batch). Each
  document owns all of its per-run state — result, overrides, previews,
  selection, active panels — and runs as one independent
  `/anonymize/stream` request; up to `MAX_CONCURRENT_STREAMS` (5) stream at
  once and the rest wait as `queued`. All entity/preview/export actions
  operate on the **active** document.
- **`settings.ts`** — expert mode + keep-original-filenames. The *only* store
  that touches `localStorage`.
- **`toast.ts`** — global toast queue.

> **Privacy rule: never write document content or results to `localStorage` /
> `sessionStorage`.** Theme and UI preferences are fine; anything derived from
> a document is not.

### Services (`services/`)

`api.ts` holds the shared axios instance; **components never import it**.
Call `anonymizeApi` / `statusApi`, or the streaming helpers in
`anonymizeStream.ts` (which speak `fetch` + NDJSON because axios cannot stream
a response body in the browser). Add a function to the matching module rather
than reaching for `api` directly.

### Components

- **`components/common/`** — the primitives copied from llmaixweb:
  `BaseButton`, `StatusBadge`, `ProgressBar`, `LoadingSpinner`, `ChipsInput`,
  `ToastContainer`/`ToastItem`. Reuse before re-implementing.
- **`components/anonymizer/`** — the product:
  - `InputPanel.vue` — dropzone + paste area + advanced settings + submit.
  - `PolicyEditor.vue` — per-type transformation selects, custom rules.
  - `ProcessingCard.vue` / `BatchProgress.vue` — streamed progress.
  - `ResultView.vue` — the result shell: status headline, export menu, panel
    switcher, the panel grid, entity summary, warnings.
  - `EntityHighlights.vue` — the source-review view. Renders
    `buildHighlightSegments()` output; marks carry `data-entity-index` and
    `data-start` (used for selection → offset mapping *and* by the e2e specs).
  - `EntityDetailPanel.vue` — preserve / redact / change type / reset.
  - `PdfAreaEditor.vue` — draw blackout regions on the original pages.
  - `DocumentBar.vue`, `WarningsList.vue`.

### Frontend conventions

- **Accessibility: never color alone.** Every highlight, badge, and status
  carries a visible text label or an `aria-label` (see `utils/entityLabels.ts`).
- **UI language is German.** Backend error `detail` strings are English and are
  mapped to German in `utils/errors.ts` — add new cases there, not inline in
  components.
- `defineProps<Props>()` + `withDefaults(...)`, `defineEmits<{...}>()`,
  `defineModel<T>()`. One `Props` interface per component, importing shared
  types from `@/types`.
- Dark mode is the Tailwind `class` strategy; `App.vue` owns the toggle and
  writes `localStorage['darkMode']`. Style variants with `dark:` utilities.
- **Verification gate:** `npm run check` (prettier + eslint + `vue-tsc
  --noEmit`, zero errors) **and** `npm run build` must pass before committing.

---

## Evaluation harness

`backend/src/evaluation/` is a standalone CLI, not part of the web app:

```bash
uv run python -m backend.src.evaluation.run \
    --input annotations.jsonl --output evaluation-results.json --detectors rules,llm
```

Inputs: our JSONL format or INCEpTION UIMA-CAS JSON exports (the LLMAIx
annotation format) — files, directories, or `.zip`. Metrics: character-level
P/R/F1 with LLMAIx-compatible semantics, span-level exact & overlap, per-type
breakdown, and — most prominently — **document-level leakage** (% of documents
with ≥1 leaked character). `--mode redaction` scores what the policy actually
masks; `--restrict-to-gt-types` gives fair precision when the ground truth
covers a subset of types.

**The report contains no literal entity text by default.**
`--include-sensitive-text` opts into a debugging report that does — never
commit its output.

---

## Testing

### Backend (pytest)

```bash
uv run pytest                                             # the whole suite
uv run pytest --cov=backend/src --cov-report=term-missing # with coverage
```

`backend/tests/conftest.py` sets `ENV_PATH` to a nonexistent file **before any
backend import**, so a developer's `backend/.env` (which may hold real
endpoints) can never leak into a test run. Keep that invariant.

- `tests/unit/` — recognizers, grounding (multiple occurrences, not-found,
  normalized fallback), chunk boundaries, overlap resolution, right-to-left
  application, consistent tags, override precedence, the source-unchanged
  invariant, safe-logger rejection, PDF export, vision OCR, evaluation metrics.
- `tests/integration/` — the API through `TestClient`, plus `test_llm_e2e.py`
  driving the full pipeline against `tests/fake_llm.py` (an in-process fake
  OpenAI-compatible server).
- `tests/files/` — **only clearly synthetic documents**, each headed
  `SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION`.

### Frontend (Vitest + jsdom)

```bash
npm test            # vitest run (CI)
npm run test:watch
```

Specs sit next to the code as `*.test.ts` (`utils/`, `composables/`,
`services/`, `stores/`). Config: `vitest.config.ts` at the repo root, kept
separate from `frontend/vite.config.ts` so the test toolchain stays out of the
production bundle. Coverage today is the pure helpers, the composables, and
the settings store; component-level coverage is not set up.

### End-to-end + documentation screenshots (Playwright)

```bash
npm run test:e2e      # smoke: fake LLM + real backend + Vite, full workflow
npm run screenshots   # regenerates docs/assets/screenshots/*.png
```

See `e2e/README.md` for the server wiring. Both suites run the **real**
detector stack (`rules,llm`) with only the LLM endpoint faked
(`e2e/support/fake-llm.mjs`), so grounding, chunking, and the re-check are
genuinely exercised. Re-run `npm run screenshots` after any UI change that
affects a documented screen.

---

## Documentation site & governance

User- and operator-facing documentation lives in `docs/` and is built with
**MkDocs Material** (`mkdocs.yml`). It is the single source of truth; the root
`README.md` is a short landing page that links into it.

```bash
uv run --only-group docs mkdocs serve     # http://127.0.0.1:8000
uv run --only-group docs mkdocs build
```

Sections: Getting started, User guide, Operations, Evaluation, Security &
governance (`SECURITY.md`, `THREAT_MODEL.md`, `DATA_FLOW.md`,
`DATA_RETENTION.md`, `RISK_REGISTER.md`, `DPIA_TEMPLATE.md`), Development.

**When you change user-facing behavior, config, or the workflow, update the
relevant page under `docs/`** — that is where users and operators read it, not
the README. Screenshots in `docs/assets/screenshots/` are generated, never
hand-captured; avoid citing exact numbers from an image in prose, since they
drift when the images regenerate.

Governance files: `LICENSE` (AGPL-3.0-or-later — note `pymupdf` is AGPL and
blocks any future MIT relicense), `THIRD_PARTY_NOTICES.md`, `CITATION.cff`,
`CHANGELOG.md` (Keep a Changelog; user/setup-facing entries only — skip
internal refactors, tests, CI), `.github/SECURITY.md`.

---

## CI workflows

`.github/workflows/`:

| Workflow | What it does |
|---|---|
| `tests.yml` | Backend ruff lint/format + pytest with a coverage floor; frontend `npm run check`, Vitest, build; Playwright e2e smoke. |
| `docs.yml` | Builds the MkDocs site; deploys to GitHub Pages on `main`. |
| `security.yml` | CodeQL, `pip-audit` + `npm audit`, Trivy filesystem scan, license check. Mostly informational. |
| `docker-publish.yml` | Builds both images (amd64+arm64); pushes to `ghcr.io/katherlab/deidentifier-*` on a published release. |

> **All four are currently `workflow_dispatch`-only.** The repository is
> private, where Actions minutes are billed; the real `push`/`pull_request`
> triggers sit commented out at the top of each file, ready to be uncommented
> when the repo goes public. **Run the equivalent commands locally before
> pushing** — nothing gates a commit automatically right now.

`.github/dependabot.yml` (weekly github-actions/uv/npm updates) is active:
Dependabot does not consume Actions minutes.

---

## Releasing

1. Bump the version in `package.json`, `pyproject.toml`, `CITATION.cff`, and
   the `APP_VERSION` default in `core/config.py` (what `/api/v1/status`
   reports).
2. `uv lock` if dependencies changed; re-run
   `./scripts/generate-third-party-notices.sh` if production dependencies
   changed.
3. Move the `[Unreleased]` entries in `CHANGELOG.md` into a dated section and
   add the compare links.
4. Run the full local gate below, including `npm run test:e2e`.
5. `git tag v0.2.0 && git push origin v0.2.0`, then publish the release —
   which is what `docker-publish.yml` reacts to (currently a manual run).

---

## Docker

```bash
docker compose up -d --build                                  # → http://localhost:8080
docker compose -f compose.yml -f compose.dev.yml up --build    # dev: hot reload + :8000
docker compose -f compose.yml -f compose.unlimited-ocr.yml up -d  # + GPU OCR sidecar
```

`APP_ENV` defaults to **production** in `compose.yml`: docs disabled, unsafe
configurations refuse to start. The backend publishes **no port** (the
frontend's nginx proxies `/api/` internally), runs **read-only with no
volumes**, and both containers are non-root. Configuration is read from
`backend/.env` at runtime and never baked into an image. Works with Docker or
Podman.

---

## Conventions

- Backend: `snake_case` files/functions, `PascalCase` models/schemas. Frontend:
  `PascalCase.vue`, `camelCase` identifiers.
- Domain logic lives in `utils/`; `services/` is for **external integrations
  only** (llmaixweb convention).
- Each OCR/LLM service class carries its own `*Error` exception with a
  `status_code`, and endpoints translate those to `HTTPException` — raw
  upstream errors are never echoed to the client.
- All outbound HTTP: `follow_redirects=False`, explicit timeouts, sanitized
  error messages (SSRF hardening).
- Lint/format:

```bash
uv run ruff check backend/ && uv run ruff format --check backend/
npm run check && npm run build
```

### The full local gate

```bash
uv run ruff check backend/ && uv run ruff format --check backend/
uv run pytest
npm run check && npm test && npm run build
npm run test:e2e            # when you touched the API or the UI flow
```

---

## Common pitfalls

- **Offsets.** Backend offsets are Unicode code points. Any new frontend code
  that maps offsets to DOM text must go through `Array.from(...)`, like
  `utils/textSegments.ts` — `String.prototype.slice` silently breaks on astral
  characters.
- **Policy drift.** `frontend/utils/policy.ts` mirrors backend
  `DEFAULT_POLICY`. Requests carry only deviations, so a drifted mirror sends
  *nothing* and displays a transformation the backend never applied.
- **Silent degradation.** Never catch a `DetectorError` and continue with
  fewer detectors, and never let a failed export produce an unverified PDF.
  Failing loudly is the feature.
- **The cache is not persistence.** A 410 is normal; the frontend re-posts the
  source text. Don't "fix" it by extending the TTL indefinitely or writing to
  disk.
- **Content in logs.** See "Safe logging" above.
- **Test fixtures.** Only synthetic documents, marked as such — they end up in
  the repository, the test output, and (via the screenshot harness) the public
  documentation site.
- **`APP_ENV=production` refuses unsafe configs.** If the container exits at
  startup, read the `Refusing to start:` message before changing anything else.

---

## When adding a feature

1. **Schema** → `schemas/entities.py` (domain vocabulary) or
   `schemas/anonymize.py` (request/response contract).
2. **Domain logic** → a module under `utils/`, pure where possible; an
   external call goes in `services/` with its own `*Error`.
3. **Endpoint** → a module under `routers/v1/endpoints/`, registered in
   `routers/v1/api.py`.
4. **Config** → field on `Settings` + documented block in `.env.example`.
5. **Frontend** → mirror the type in `frontend/types/anonymizer.ts`, add the
   call to a `services/*Api.ts` module, put state on the active document in
   `stores/session.ts`, build the UI from `components/common/` primitives.
6. **Tests** → a unit test for the logic, an integration test for the route,
   a Vitest spec for a new frontend helper, and an e2e assertion if it changes
   the user-visible workflow.
7. **Docs** → the affected page under `docs/`, plus a `CHANGELOG.md` entry if
   it affects users or setup. Re-run `npm run screenshots` if a documented
   screen changed.
