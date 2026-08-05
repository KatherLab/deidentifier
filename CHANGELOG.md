# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries are brief and describe what affects users or setup — features,
configuration and breaking changes, notable fixes. Internal refactors, tests,
documentation, and CI work are left out.

## [Unreleased]

## [0.1.0] — 2026-08-05

First tagged version.

### Added

**Pipeline**

- Immutable-source architecture: detectors propose character spans,
  deterministic code applies every edit, and no generative model ever rewrites
  a document.
- Rule-based German recognizers for structured identifiers (e-mail, URL,
  phone/fax, IBAN, postal codes, numeric dates, labelled IDs).
- LLM detector behind any OpenAI-compatible endpoint, with overlapping
  chunking, multi-pass detection (`LLM_DETECTION_PASSES`), and
  prompt-injection hardening.
- One recall-first default policy with five transformations (`TYPE_MASK`,
  `CONSISTENT_TAG`, `GENERALIZE`, `REMOVE`, `PRESERVE`); birth dates and ages
  are masked by default, clinical dates preserved.
- Leakage validation on the output, including an optional LLM audit
  (`LLM_RECHECK_ENABLED`). Produces `PASS` / `REVIEW_REQUIRED` / `FAIL` and
  never edits the output.

**Input and OCR**

- Pasted text plus `.txt`, `.docx` and `.pdf` uploads; scanned PDFs detected
  via an embedded-text probe.
- OCR engines: `docling_tesseract` and `llm_vision` (Unlimited-OCR via vLLM),
  with a `force_ocr` option for PDFs whose text layer is unusable.
- Local `pypdf` fallback when docling-serve is unset or unreachable, so the app
  runs with no external services at all.

**Interface**

- Single-screen input with drag-and-drop, parallel multi-document batches, and
  streamed pipeline progress.
- Result view with entity highlights, per-entity preserve/redact/retype, manual
  redaction of arbitrary selections, the anonymized text, and a redacted-PDF
  preview.
- Advanced settings: per-type policy, always-redact and never-redact term
  lists, an extra instruction for the LLM detector, and forced OCR.
- Expert mode for diagnostics (detector, confidence, offsets, timings).
- Exports: clipboard, `.txt`, redacted `.pdf`, and `.zip` for a batch, with an
  opt-in to keep original filenames.
- Interface languages: German, English, French and Spanish. The app opens in
  the browser's language, falls back to German, and the header's globe button
  switches it. Backend warnings and notices are translated too.
- Output language of the anonymized document (advanced settings, or
  `output_language` on the API): placeholders, the AI re-check's notes, and the
  export file name follow the language chosen for the run. It is fixed when
  anonymization starts, so switching the interface language while reviewing
  never rewrites a finished document.

**Redacted-PDF export**

- True redaction for native PDFs with post-export verification — an export that
  cannot be verified is refused.
- Reconstruction from the anonymized text at OCR layout positions for scanned
  PDFs, with the original pixels discarded.
- User-drawn blackout areas for signatures, logos, and stamps.

**Evaluation**

- Standalone harness (`python -m backend.src.evaluation.run`) reading our JSONL
  format or INCEpTION UIMA-CAS exports, reporting character- and span-level
  metrics plus document-level leakage.

**Deployment and privacy**

- Docker Compose deployment (backend + nginx frontend, with a GPU
  Unlimited-OCR overlay). The backend publishes no port, runs read-only with no
  volumes, and persists nothing.
- Production mode refuses to start with the mock detector or insecure content
  logging enabled.
- A structured logger that drops document-content fields, `Cache-Control:
  no-store` on content responses, and no analytics, telemetry, or CDN.
- Deployment banner above the header (e.g. "Research Use Only!"), configured
  with `BANNER_ENABLED`, `BANNER_TEXT` and `BANNER_COLOR`.
- Documentation site (MkDocs Material) under `docs/`:
  `uv run --only-group docs mkdocs serve`.

[Unreleased]: https://github.com/KatherLab/deidentifier/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/KatherLab/deidentifier/releases/tag/v0.1.0
