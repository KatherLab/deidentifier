# German Clinical Document Anonymizer — Design v1

> The original, much larger plan is archived in `DESIGN_DOCUMENT_original_chatgpt.md`.
> This version is trimmed to a shippable v1 and aligned with the structure and
> conventions of the sibling project **llmaixweb** (cloned into `./llmaixweb`
> for reference — not part of this repo). Cut features are listed at the end
> under "Deferred".

## Objective

A locally deployable web app that anonymizes German clinical documents.
The default experience is a single screen: drop a PDF (or paste text), click one
button, get anonymized text out — with a review view showing exactly what was
redacted and why.

This is an internal evaluation tool, not a certified anonymization product.
The README must state that results do not establish legal anonymity.

## Core principles

1. **Immutable source, spans only.** No generative model ever rewrites the
   document. Detectors (including LLMs) only *propose* entities; deterministic
   code applies all edits via character offsets on the unchanged source text.
2. **Recall over precision.** A missed name is worse than an over-redacted word.
   Defaults over-redact; preservation is opt-in per entity in the review UI.
3. **Simple mode is the app**, not a mode. No policy selectors or instruction
   fields on the main screen. One sensible default policy; per-entity overrides
   happen after processing, in the review view.
4. **Configurable endpoints, local by default.** All model/OCR backends are
   admin-configured base URLs (same env-var names as llmaixweb where they
   overlap). The UI shows a clear banner when any configured endpoint is not
   local/private, so users know where document content flows.
5. **llmaixweb conventions, minus the weight.** Same layout, config pattern,
   service style, frontend stack — but no database, no Celery/Redis, no S3,
   no auth (runs behind the hospital's auth proxy), no Alembic.

## Pipeline

```text
Document (PDF / DOCX / TXT / pasted text)
  → extraction (pypdf text probe → docling-serve, or OCR route for scans)
  → rule-based detection (structured identifiers)
  → LLM detection (prompted, JSON entities → grounded to offsets)
  → optional privacy-filter second net
  → span merging & overlap resolution
  → deterministic transformation
  → leakage validation (re-scan of output)
  → result + review UI
```

## Technology (mirrors llmaixweb)

- Python 3.13, managed with **uv** (`pyproject.toml` + `uv.lock`, ruff for
  lint/format)
- FastAPI + Pydantic v2; pydantic-settings for config
- **Vue 3 + TypeScript + Vite**, Pinia, TailwindCSS v4, lucide icons,
  hand-rolled `components/common/` primitives (copy the needed ones —
  `BaseButton`, `BaseModal`, `StatusBadge`, toast — from llmaixweb)
- `openai` SDK for all OpenAI-compatible endpoints (LLM detection, vision OCR)
- pypdf (text probe), python-docx; docling-serve via HTTP for extraction/OCR
- pytest (backend); `npm run check` gate (format, lint, type-check) on frontend
- Docker Compose with the same layered-file pattern (`compose.yml` +
  `compose.dev.yml` + optional `compose.vllm.yml` / `compose.deepseek.yml`)

## Repository structure

Mirrors llmaixweb, with the DB/queue/auth layers removed. Anonymization domain
logic lives in `utils/` (llmaixweb convention: `services/` is for external
integrations only).

```text
deidentifier/
├── AGENTS.md                  # canonical agent/dev guide; CLAUDE.md is a stub that @-includes it
├── CLAUDE.md
├── README.md, DEVELOPER.md, SECURITY.md
├── .env.example               # documents every variable (the config reference)
├── pyproject.toml, uv.lock, pytest.ini
├── package.json               # frontend scripts (dev/check/build)
├── compose.yml, compose.dev.yml, compose.vllm.yml, compose.deepseek.yml
├── Dockerfile.backend, Dockerfile.frontend
├── backend/
│   ├── tests/                 # pytest: unit/, integration/, files/ (synthetic fixtures)
│   └── src/
│       ├── main.py            # module-level `app = FastAPI(...)`, lifespan, router wiring
│       ├── core/
│       │   └── config.py      # Settings(BaseSettings), ENV_PATH pattern
│       ├── middleware/        # error_handlers, security_headers (copy from llmaixweb)
│       ├── routers/v1/
│       │   ├── api.py
│       │   └── endpoints/     # anonymize.py, status.py, health.py
│       ├── schemas/           # entities.py, anonymize.py (grouped by domain)
│       ├── services/          # external integrations, copied/adapted from llmaixweb:
│       │   ├── docling_serve_client.py
│       │   ├── mistral_ocr_service.py
│       │   ├── llm_vision_ocr_service.py
│       │   └── pdf_text_probe.py
│       └── utils/             # domain logic
│           ├── extraction.py  # routing: probe → docling / OCR engine dispatch
│           ├── rules.py       # German regex/context recognizers
│           ├── llm_detection.py   # prompt, structured output, chunking
│           ├── grounding.py   # LLM strings → validated source offsets
│           ├── resolver.py    # merge & overlap resolution
│           ├── transformation.py  # pure transform functions
│           ├── leakage.py     # output validation pass
│           ├── policy.py      # default policy + override handling
│           └── safe_logging.py
├── frontend/                  # llmaixweb layout: src files directly under frontend/
│   ├── App.vue, main.ts, index.html, vite.config.ts
│   ├── nginx.conf, docker-entrypoint.sh
│   ├── components/            # common/ (copied primitives), anonymizer/ (DropZone,
│   │                          #   ResultView, EntityHighlights, EntityDetailPanel, WarningsList)
│   ├── composables/           # useToast, useFileDownload (copy from llmaixweb)
│   ├── views/                 # AnonymizerView.vue (single routed view)
│   ├── stores/                # session.ts (current result/overrides), toast.ts
│   ├── services/              # api.ts (axios) + anonymizeApi.ts, statusApi.ts
│   ├── types/                 # TS mirrors of Pydantic schemas
│   └── utils/
└── llmaixweb/                 # reference clone only — excluded from tooling, not shipped
```

Not carried over from llmaixweb: `models/`, `db/`, `alembic/`, `celery/`,
`dynamic_settings.py` + `SETTINGS_META`, auth/SSO, S3/rustfs, websockets,
i18n (German-focused tool; revisit later), Redis.

## Extraction & OCR

PDFs — including scanned ones — are the primary format. Reuse llmaixweb's
service classes and routing logic (`utils/preprocessing.py` there) in
simplified form; each engine stays an independent service class with its own
`*Result` dataclass and `*Error` exception, selected by string dispatch.

Routing (`utils/extraction.py`, mode `auto`):

1. TXT: UTF-8 (+BOM), reject binary. DOCX: paragraphs, tables, headers,
   footers via python-docx; warn on text boxes / comments / tracked changes.
2. PDF: `pdf_text_probe.has_embedded_text(...)` (pypdf, char threshold per
   `DOCLING_MIN_EXTRACTED_CHARS_PDF`).
3. Sufficient embedded text → docling-serve `convert_pdf_no_ocr` when
   `DOCLING_SERVE_URL` is configured; otherwise (or when docling-serve is
   unreachable) local pypdf extraction with page mapping, so the app works
   out of the box without any services.
4. Scanned (or `force_ocr`) → configured OCR engine:
   - `docling_tesseract` — docling-serve with Tesseract
   - `mistral_ocr` — Mistral-OCR-compatible API (`MISTRAL_API_BASE`; covers
     the real API and the self-hosted DeepSeek-OCR-2 + katdocextract stack
     from `compose.deepseek.yml`)
   - `llm_vision` — OpenAI-compatible vision model (`VISION_OCR_API_BASE`),
     page images via pymupdf/Pillow, concurrent per-page
   - `none` — scanned PDFs rejected with a clear message

Extraction result:

```python
class ExtractedDocument(BaseModel):
    text: str
    source_type: str            # "txt" | "docx" | "pdf" | "pdf-ocr" | "paste"
    pages: list[PageRange] = [] # page → char-offset mapping when known
    warnings: list[str] = []
```

Page mapping may be approximate for OCR; record that as a warning. Never claim
a scanned document was anonymized if no text was extracted.

## Canonical entity schema

All detectors return exactly this structure. Every span is validated against
the source (`source_text[start:end] == text`); invalid spans are rejected with
a logged warning (category only, never content).

```python
class EntityType(StrEnum):
    PERSON_NAME = "PERSON_NAME"          # any person; role in metadata if known
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    OTHER_DATE = "OTHER_DATE"
    AGE = "AGE"
    ADDRESS = "ADDRESS"                  # street / postal code / city
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    URL = "URL"
    ID_NUMBER = "ID_NUMBER"              # patient/case/insurance/accession IDs
    ORGANIZATION = "ORGANIZATION"        # hospital, practice, employer, school
    PROFESSION = "PROFESSION"
    OTHER_PII = "OTHER_PII"

class EntitySpan(BaseModel):
    start: int
    end: int
    text: str
    entity_type: EntityType
    confidence: float = Field(ge=0, le=1)
    detector: str
    metadata: dict[str, str | int | float | bool] = {}
    # validator: end > start, len(text) == end - start
```

Deliberately coarse (12 types): simpler LLM prompt, policy, and UI. Sub-typing
(patient vs clinician, kind of ID) lives in `metadata` and can be promoted
later. Offsets are Unicode code points throughout; the frontend never
recomputes offsets from modified text.

## Detection

```python
class SpanDetector(Protocol):
    name: str
    async def detect(self, text: str) -> list[EntitySpan]
```

### 1. LLM detector (primary)

Based on prior paper results: a prompted LLM is the primary detector for
German clinical text.

- Any **OpenAI-compatible endpoint** (`OPENAI_API_BASE` / `OPENAI_API_KEY` /
  `LLM_MODEL`). Reuse llmaixweb's client pattern from
  `utils/info_extraction.py`: per-call `OpenAI(...)` with
  `follow_redirects=False` httpx client (SSRF hardening), configured timeout,
  sanitized error messages.
- **Structured output**: `response_format={"type": "json_schema", ...}` with
  the provider-capability profile pattern (`guided_json` fallback for
  vLLM/llama.cpp) copied from llmaixweb. Response schema:
  `[{"text": "...", "entity_type": "...", "role": "..."}]`.
  The LLM returns **strings, never offsets** — LLMs are unreliable at offsets.
- **Grounding** (`utils/grounding.py`): deterministic code locates each
  returned string in the source — exact match on all occurrences, fallback to
  whitespace-normalized match, else a validation warning ("LLM reported an
  entity that could not be located"). All matches of the same string get the
  same type.
- **Chunking:** overlapping chunks (default ~8k chars, 500 overlap); results
  grounded per-chunk against the full source and deduplicated. No characters
  lost or double-processed.
- Malformed JSON → one retry (llmaixweb also retries with raised max_tokens on
  length-truncation — copy that), then fail the request with a clear error.
  Never silently return "no entities found".

### 2. Rule-based detector

German-oriented regex/context recognizers for structured data the LLM might
format-drift on: emails, URLs, phone/fax, IBANs, postal codes, numeric dates,
and labelled identifiers (`Pat.-Nr.`, `Fallnummer`, `Versichertennummer`,
`Aufnahmenummer`, `geb.`, `Tel.` …). Stable rule IDs (`de.email.v1`,
`de.patient_id.labelled.v1`). Context-aware: a bare number is not an ID unless
near a label. Never auto-redact all numbers.

### 3. Privacy-filter detector (optional second net)

Adapter for `openai/privacy-filter` (1.5B token classifier, Apache 2.0),
served behind a configurable endpoint. Primarily English, so it is **off by
default** and used — when enabled — as an additional detector and in the
leakage-validation pass, not as the primary German detector.

### 4. Mock detector

Detects fixed fixture strings (`Max Mustermann`, `PAT-123456`, …) for tests
and offline development. Refused in production config.

### Merging & overlap resolution

Deterministic, before transformation (`utils/resolver.py`):

1. Exact duplicates merge (provenance kept in metadata, confidence combined
   conservatively — take the max).
2. Overlapping spans: keep the longer span; the contained span is recorded as
   supporting evidence. A labelled identifier beats a partial numeric match.
3. Explicit user overrides (preserve/redact from the review UI) beat everything.
4. One transformation per character; apply right-to-left (descending start).
5. Every conflict resolution is recorded and inspectable in the review UI.

## Policy & transformation

**One built-in default policy** (recall-first). No policy selector, no
natural-language instruction compiler. Adjustments happen as per-entity
overrides in the review UI, which re-run the deterministic transformation —
never by mutating the output.

Default policy:

| Entity type   | Transformation                                  |
|---------------|-------------------------------------------------|
| PERSON_NAME   | CONSISTENT_TAG → `[PERSON_1]`, `[PERSON_2]` …   |
| DATE_OF_BIRTH | GENERALIZE → year only (`01.02.1980` → `1980`)  |
| OTHER_DATE    | PRESERVE (clinical timelines stay useful)       |
| AGE           | PRESERVE                                        |
| ADDRESS       | TYPE_MASK → `[ADRESSE]`                         |
| PHONE/EMAIL/URL | TYPE_MASK                                     |
| ID_NUMBER     | TYPE_MASK → `[ID]`                              |
| ORGANIZATION  | TYPE_MASK (preserve via override when wanted)   |
| PROFESSION    | TYPE_MASK                                       |
| OTHER_PII     | TYPE_MASK                                       |

Transformations are pure functions: `TYPE_MASK`, `CONSISTENT_TAG` (same
normalized string → same tag; no surname-only coreference), `GENERALIZE`
(DOB → year), `REMOVE` (`[GESCHWÄRZT]`), `PRESERVE`. That's all for v1.

## Leakage validation

Separate pass over the anonymized output (`utils/leakage.py`):

1. Every detected non-preserved entity's original text must not remain
   (checked for all its occurrences).
2. Rule detectors re-run on the output at sensitive settings.
3. Suspicious labelled fields (`Patient:`, `Name:`, `Geburtsdatum:` followed
   by non-redacted content) are flagged.
4. Optionally, the LLM re-checks the output ("does PII remain? return JSON"),
   and/or privacy-filter runs — both grounded the same way, warnings only.

Result: `PASS` | `REVIEW_REQUIRED` | `FAIL` with located warnings. Validation
never silently edits the output; warnings surface in the UI.

## API

Same router style as llmaixweb (`routers/v1/endpoints/`, mounted under
`/api/v1`), no auth (hospital proxy in front):

- `POST /api/v1/anonymize` — multipart (`file`) or JSON (`text`), plus
  optional `overrides` (per-span decisions from the review UI, keyed by
  offsets+text). Returns anonymized text, entities with applied
  transformations, validation result, timings.
- `GET  /api/v1/status` — configured backends (OCR route, LLM endpoint
  reachable, privacy-filter enabled), readiness; flags non-local endpoints.
  Never returns file paths or keys.
- `GET  /health/live`, `GET /health/ready`

Limits: upload default 20 MB (PDF scans are big), extracted text default
500k chars, extensions txt/docx/pdf, clear errors for password-protected /
malformed / unsupported files, size-capped streamed uploads (413 before
buffering, as in llmaixweb). `Cache-Control: no-store` on all content routes.

Re-running with overrides re-uses the request's detection results held in
process memory with a short TTL (no persistence); if expired, detection
re-runs.

## Frontend

Vue 3 SPA following llmaixweb conventions: components never import the axios
instance directly (typed `services/*Api.ts` modules only), primitives from
`components/common/`, Tailwind with class-based dark mode. **No localStorage
for document content** (llmaixweb's token/darkMode usage is fine; content is
not).

**Main screen** (`AnonymizerView.vue`): title, local-processing notice (plus
the external-endpoint banner when applicable), drag-and-drop zone + paste
area, one **Anonymisieren** button. Nothing else.

**Result screen:**

1. Anonymized text with copy + download `.txt`.
2. Status badge: Passed / Review required / Failed.
3. Toggle to source-review view: entities highlighted over the immutable
   source text; color + text label per action (redacted / generalized /
   tagged / preserved / warning) — never color alone.
4. Click an entity → details (type, detector, confidence, replacement) and
   actions: preserve / redact / change type. Any change re-runs transformation
   server-side and refreshes the result.
5. Entity counts by type; validation warnings listed and clickable.

Friendly errors for: unsupported file, too large, scanned PDF with OCR
disabled, extraction failure, LLM endpoint unreachable, review-required
output. No stack traces.

## Security & privacy

- Document content flows only to admin-configured endpoints; UI banner when
  any endpoint is non-local.
- No analytics, no third-party fonts/scripts/CDNs, no telemetry.
- No content in logs: structured safe logger that rejects fields named
  `text`, `content`, `prompt`, `filename`, `entity_text`, `anonymized_text`
  unless an insecure dev flag (default false, loud startup warning) is set.
  Logs carry request ID, timings, lengths, status, error category only.
  Correlation-ID request context as in llmaixweb.
- No persistence: in-memory processing, temp files with random names deleted
  in `finally`, no database, `no-store` headers, restrictive CORS,
  upload/MIME validation.
- SSRF guardrails on all outbound clients (`follow_redirects=False`, never
  echo raw upstream errors) — copy `utils/url_safety.py` patterns.
- Production mode refuses to start with mock detector or insecure logging
  enabled.
- Containers non-root; frontend nginx serves the SPA and reverse-proxies
  `/api/` to the backend (llmaixweb's two-image pattern); Swagger disabled in
  production; deployable behind the hospital's auth proxy.

## Configuration

`Settings(BaseSettings)` in `core/config.py`, llmaixweb pattern: `ENV_PATH`
env var selects the `.env` file (default `backend/.env`), `case_sensitive`,
`extra="ignore"`, every variable documented in `.env.example`. **No**
dynamic-settings/DB layer, **no** network checks in `__init__` (readiness is
reported via `/health/ready` instead of failing startup). Env names match
llmaixweb where the concept overlaps:

```env
APP_ENV=development
APP_MAX_UPLOAD_MB=20
APP_MAX_TEXT_CHARS=500000
APP_ALLOW_INSECURE_CONTENT_LOGGING=false

# Primary PII detection LLM (OpenAI-compatible)
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=
LLM_MODEL=
LLM_REQUEST_TIMEOUT_SECONDS=120
LLM_CHUNK_CHARS=8000
LLM_CHUNK_OVERLAP=500

# Extraction / OCR
DOCLING_SERVE_URL=http://localhost:5001
DOCLING_MIN_EXTRACTED_CHARS_PDF=100
PDF_MAX_PAGES_FOR_TEXT_PROBE=5

# OCR engine for scanned PDFs: none | docling_tesseract | mistral_ocr | llm_vision
OCR_ENGINE=none
MISTRAL_API_BASE=
MISTRAL_API_KEY=
MISTRAL_OCR_MODEL=mistral-ocr-latest
VISION_OCR_API_BASE=
VISION_OCR_API_KEY=
VISION_OCR_MODEL=

# Optional second-net detector
PRIVACY_FILTER_ENABLED=false
PRIVACY_FILTER_BASE_URL=

# Detectors: comma-separated (mock | rules | llm | privacy_filter)
DETECTORS=rules,llm
```

## Docker deployment

llmaixweb's layered-compose pattern, minus the DB/queue/storage services:

- `compose.yml` — `backend`, `frontend` (nginx-unprivileged), `docling-serve`
  (+ models-init)
- `compose.dev.yml` — source mounts + reload
- `compose.vllm.yml` — adds a `vllm` GPU service (OpenAI-compatible; usable as
  detection LLM and/or vision OCR) — reuse llmaixweb's file
- `compose.deepseek.yml` — adds the self-hosted Mistral-OCR-compatible stack
  (DeepSeek-OCR-2 vllm + katdocextract) — reuse llmaixweb's file

No postgres, redis, rustfs, or worker containers.

## Testing

pytest only for v1 (no Vitest/Playwright yet; frontend gate is
`npm run check` + `npm run build`):

- **Unit:** every regex recognizer; offsets with umlauts/ß/combining chars/
  non-breaking spaces; LLM-string grounding (multiple occurrences, not-found,
  normalized fallback); chunk merge at boundaries; overlap resolution;
  right-to-left application; consistent tags; DOB generalization; override
  precedence; source-unchanged invariant; safe-logger rejection.
- **Integration (mock detector + real rules):** anonymize text & file uploads
  (txt/docx/pdf), scanned-PDF routing/rejection, oversized/unsupported
  rejection, endpoint-unreachable behavior, no-store headers.
- **Evaluation harness (kept — it feeds the papers and a future fine-tuned
  model):** `python -m backend.src.evaluation.run --input annotated.jsonl
  --output out.json` reporting exact/overlap/character-level P/R/F1, per-type
  metrics, and — most prominently — **document-level leakage** (% documents
  with ≥1 missed entity). Annotated data doubles as future fine-tuning data.

Fixtures in `backend/tests/files/`: ~10 clearly synthetic German documents
(discharge letter, radiology report, lab text, referral, OCR-like spacing
errors, same surname for patient and physician, IDs in tables…), each headed
`SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION`.

## Milestones

1. **Vertical slice:** FastAPI skeleton (main/config/routers per llmaixweb
   layout) + Vue app with copied primitives; paste text + txt upload; rules +
   mock detectors; default policy; TYPE_MASK/CONSISTENT_TAG; result screen
   with highlights; safe logging; unit tests.
2. **LLM + PDFs:** LLM detector (structured output + grounding + chunking);
   pypdf probe + docling-serve extraction; DOCX; scanned-PDF OCR routing;
   leakage validation; per-entity overrides; validation badge.
3. **Hardening + evaluation:** remaining OCR engines (mistral_ocr,
   llm_vision); privacy-filter second net; evaluation harness + fixtures;
   Docker Compose files; production startup checks; README, SECURITY.md,
   AGENTS.md (+ CLAUDE.md stub).

## Deferred (cut from v1, revive on demand)

- Multiple preset policies and the policy selector
- Natural-language custom-instruction compiler (deterministic or LLM)
- Date shifting, partial masks, surrogate generation, age-band generalization
- Fine-grained 30-type entity taxonomy (subtypes live in metadata for now)
- Audit JSON export with keyed HMAC
- Reconstructed redacted PDF/DOCX output (plain text only in v1)
- Frontend test stack (Vitest) and Playwright e2e
- i18n (vue-i18n as in llmaixweb) — German-first UI for now
- Fine-tuned in-house detection model (enabled later by the accumulated
  annotated evaluation data — same adapter interface)
