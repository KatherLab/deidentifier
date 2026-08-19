# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries are brief and describe what affects users or setup — features,
configuration and breaking changes, notable fixes. Internal refactors, tests,
documentation, and CI work are left out.

## [Unreleased]

## [0.2.1] — 2026-08-19

### Added

- The running app version is shown at the bottom of every screen.

### Changed

- **Bereiche schwärzen** draws on the redacted pages, so the automatic
  redactions are visible while marking areas — see
  [Reviewing a result](docs/user-guide/review.md).

### Fixed

- Areas drawn on a scanned document's export only covered the text instead of
  removing it, leaving it selectable in the exported PDF.

## [0.2.0] — 2026-08-11

### Added

- `VISION_OCR_DIALECT` selects the vision-OCR model family (`unlimited_ocr`,
  `chandra`, `plain`) and supplies the prompt, token and body defaults — see
  [OCR engines](docs/operations/ocr-engines.md).

- `VISION_OCR_PROFILES` offers several OCR models at once, one pickable per
  document in the advanced settings — see
  [OCR engines](docs/operations/ocr-engines.md).

- `compose.chandra.yml` runs a datalab chandra GPU OCR sidecar, as
  `compose.unlimited-ocr.yml` does for Unlimited-OCR — see
  [OCR engines](docs/operations/ocr-engines.md).

### Changed

- `.env.example` is now a short setup worksheet that ships with the LLM
  detector enabled: fill in `OPENAI_API_BASE`/`LLM_MODEL` before first start
  (or set `DETECTORS=rules` for a look without an LLM) — see
  [Configuration](docs/operations/configuration.md).

- `LLM_REQUEST_TIMEOUT_SECONDS` now defaults to `600` instead of `120` — see
  [Configuration](docs/operations/configuration.md).

## [0.1.3] — 2026-08-07

### Fixed

- The frontend image's `linux/arm64` build crashed in CI because Node ran under
  QEMU emulation; the build stage now runs on the build host's architecture
  (and on Node 24, matching what the tests run).

## [0.1.2] — 2026-08-07

### Added

- The source review takes multiple finds at once: Ctrl/Cmd-click and
  Shift-click build a selection that can be redacted, kept, retyped or reset in
  a single re-run — see [Reviewing the result](docs/user-guide/review.md).

### Changed

- The entity actions in the source review now appear next to the selected mark
  instead of at the foot of the panel.

- The result view now says when a passage you kept will stay blacked out in the
  redacted PDF anyway, because a native PDF is redacted by searching for the
  text — see [Exporting](docs/user-guide/export.md#redacted-pdf).

### Fixed

- Addresses, phone numbers and IBANs no longer run past the end of their line
  and swallow the first word below them — a city followed by `Pat.-Nr.:` was
  redacted as `01307 Dresden\nPat`.
- A highlight covering a line break now wraps per line instead of rendering as
  one oversized box across the paragraph.

## [0.1.1] — 2026-08-06

### Security

- The frontend container mounts `/tmp` as a `tmpfs` and nginx no longer buffers
  `/api/` responses, so uploads and results are never spooled to disk. Running
  the image outside `compose.yml` requires mounting that `tmpfs` yourself — see
  [Data retention](docs/DATA_RETENTION.md).
- Request ids are no longer written to the backend log; a short hash is logged
  instead.

### Changed

- Results now expire 15 minutes after they were created rather than after last
  use, and the top bar shows the remaining time and extends it on demand. New
  `RESULT_CACHE_TTL_MINUTES`, `RESULT_CACHE_EXTENSION_MINUTES`,
  `RESULT_CACHE_MAX_LIFETIME_MINUTES` and `RESULT_CACHE_MAX_ENTRIES` — see
  [Configuration](docs/operations/configuration.md#tightening-it).
- New `DELETE /api/v1/anonymize/{request_id}`, called by the review UI when a
  document is closed so the server-side copy ends immediately.
- `.env.example` ships `DETECTORS=rules` with the LLM block commented out, so
  `cp .env.example .env && docker compose up -d --build` starts a working stack.
- Hospital units (`Klinik für Kardiologie`, `Station 4B`) are now detected as
  `ORGANIZATION` by both the LLM prompt and new rule recognizers.

### Removed

- The unimplemented `privacy_filter` detector and its `PRIVACY_FILTER_ENABLED` /
  `PRIVACY_FILTER_BASE_URL` settings.

## [0.1.0] — 2026-08-05

First tagged version.

### Added

- Anonymization of pasted text, `.txt`, `.docx` and `.pdf`, combining German
  rule-based recognizers with an LLM detector behind any OpenAI-compatible
  endpoint. Detectors only propose character spans; deterministic code applies
  every edit.
- One recall-first default policy with five transformations, plus leakage
  validation of the output reporting `PASS` / `REVIEW_REQUIRED` / `FAIL`.
- OCR for scanned PDFs via `docling_tesseract` or `llm_vision`, with a local
  `pypdf` fallback so the app runs with no external services.
- Single-screen interface with multi-document batches, streamed progress, and a
  review view for per-entity preserve/redact/retype and manual redaction.
- Advanced settings: per-type policy, always- and never-redact term lists, an
  extra LLM instruction, and forced OCR. Expert mode adds diagnostics.
- Exports: clipboard, `.txt`, verified redacted `.pdf` (with user-drawn blackout
  areas), and `.zip` for a batch.
- Interface and output languages in German, English, French and Spanish, chosen
  independently.
- Standalone evaluation harness (`python -m backend.src.evaluation.run`).
- Docker Compose deployment that publishes no backend port, runs read-only, and
  persists nothing. Production mode refuses unsafe configurations, and a
  configurable deployment banner sits above the header.
- Documentation site (MkDocs Material) under `docs/`.

[0.2.1]: https://github.com/KatherLab/deidentifier/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/KatherLab/deidentifier/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/KatherLab/deidentifier/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/KatherLab/deidentifier/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/KatherLab/deidentifier/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KatherLab/deidentifier/releases/tag/v0.1.0
