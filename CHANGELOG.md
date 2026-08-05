# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries describe what affects users or setup — new features, configuration and
breaking changes, notable fixes. Internal refactors, tests, and CI work are
left out.

## [Unreleased]

### Added

- **Documentation site** (MkDocs Material) under `docs/`, covering getting
  started, the user guide, operations, the evaluation harness, security and
  governance, and development. Build it with
  `uv run --only-group docs mkdocs serve`.
- **`AGENTS.md`** — the canonical codebase guide, with `CLAUDE.md` as a stub
  that includes it.
- **Frontend unit tests** (Vitest + jsdom): `npm test`, `npm run test:watch`.
- **End-to-end smoke test** (Playwright) driving paste → detection → override
  → export against the real backend with a deterministic fake LLM:
  `npm run test:e2e`.
- **Documentation screenshot harness**: `npm run screenshots` regenerates
  `docs/assets/screenshots/` from the synthetic fixtures.
- **CI workflows** for tests, docs, security scanning, and image publishing.
  All are `workflow_dispatch`-only while the repository is private; the
  `push`/`pull_request` triggers are commented out in each file, ready to be
  enabled when it goes public.
- `CITATION.cff`, `THIRD_PARTY_NOTICES.md`, `.github/SECURITY.md`, and this
  changelog.

## [0.1.0] — 2026-08-05

First tagged version. Milestones 1 and 2 of `DESIGN_DOCUMENT.md`, plus most of
Milestone 3.

### Added

**Pipeline**

- Immutable-source architecture: detectors propose character spans,
  deterministic code applies every edit, and no generative model ever rewrites
  a document.
- Rule-based German recognizers for structured identifiers (e-mail, URL,
  phone/fax, IBAN, postal codes, numeric dates, labelled IDs) with stable rule
  IDs and context awareness.
- **LLM detector** behind any OpenAI-compatible endpoint: structured JSON
  output, boundary-aware overlapping chunking, deterministic grounding of
  mention strings to source offsets, multi-pass detection (`LLM_DETECTION_PASSES`),
  bisecting retry on truncated output, and prompt-injection hardening.
- Deterministic span merging and overlap resolution — exactly one
  transformation per character.
- One recall-first default policy with five transformations (`TYPE_MASK`,
  `CONSISTENT_TAG`, `GENERALIZE`, `REMOVE`, `PRESERVE`); birth dates and ages
  are masked by default, clinical dates preserved.
- Leakage validation on the output: residual-identifier scan, rule
  re-detection, labelled-field check, and an optional LLM audit that also
  assesses holistic re-identification risk (`LLM_RECHECK_ENABLED`). Produces
  `PASS` / `REVIEW_REQUIRED` / `FAIL` and never edits the output.

**Input and OCR**

- Pasted text plus `.txt`, `.docx` and `.pdf` uploads; scanned PDFs detected
  via an embedded-text probe.
- OCR engines: `docling_tesseract` and `llm_vision` (Unlimited-OCR via vLLM),
  with a `force_ocr` option for PDFs whose text layer is unusable. Empty pages
  are retried with a fallback prompt and otherwise fail closed.
- Local `pypdf` fallback when docling-serve is unset or unreachable, so the app
  runs with no external services at all.

**Interface**

- Single-screen input with drag-and-drop, parallel multi-document batches, and
  streamed pipeline progress.
- Result view with the source review (entity highlights, per-entity
  preserve/redact/retype, manual redaction of arbitrary selections), the
  anonymized text, the original document, and a redacted-PDF preview.
- Advanced settings: per-type policy, always-redact and never-redact term
  lists, an extra instruction for the LLM detector, and forced OCR.
- Expert mode for diagnostics (detector, confidence, offsets, timings,
  warning categories).
- Exports: clipboard, `.txt`, redacted `.pdf`, and `.zip` for a batch, with an
  opt-in to keep original filenames.

**Redacted-PDF export**

- True redaction for native PDFs (text removed, character boxes covered) with
  post-export verification — an export that cannot be verified is refused.
- Reconstruction from the anonymized text at OCR layout positions for scanned
  PDFs, with the original pixels discarded.
- User-drawn blackout areas for signatures, logos, and stamps.

**Evaluation**

- Standalone harness (`python -m backend.src.evaluation.run`) reading our JSONL
  format or INCEpTION UIMA-CAS exports, reporting character-level and
  span-level metrics with LLMAIx-compatible semantics, a per-type breakdown,
  and — most prominently — document-level leakage.

**Deployment and privacy**

- Docker Compose deployment (backend + nginx frontend, with a GPU
  Unlimited-OCR overlay). The backend publishes no port, runs read-only with
  no volumes, and persists nothing.
- Production mode refuses to start with the mock detector or insecure content
  logging enabled.
- A structured logger that drops document-content fields, `Cache-Control:
  no-store` on content responses, and no analytics, telemetry, or CDN.

[Unreleased]: https://github.com/KatherLab/deidentifier/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/KatherLab/deidentifier/releases/tag/v0.1.0
