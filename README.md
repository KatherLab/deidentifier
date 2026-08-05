# Medical Document Anonymizer

A locally deployable web app that anonymizes German clinical documents: drop a
document (or paste text), click one button, get anonymized text out — with a
review view showing exactly what was redacted and why.

> **This is an internal evaluation tool.** Its output does **not** establish
> legal anonymization. Results must be reviewed by a human, and anonymization
> quality must be validated locally before any downstream use.

📖 **[Full documentation](https://katherlab.github.io/deidentifier/)** —
getting started, user guide, operations, evaluation, security, development.

## How it works

No generative model ever rewrites the document. Detectors — rule-based German
recognizers and a prompted LLM behind any OpenAI-compatible endpoint — only
*propose* character spans; deterministic code applies the replacements on the
immutable source text, and an independent leakage-validation pass re-scans the
output and reports `PASS` / `REVIEW_REQUIRED` / `FAIL`.

```text
Document → extraction → rule + LLM detection → span merging
        → deterministic transformation → leakage validation → review UI
```

Pasted text plus `.txt`, `.docx` and `.pdf` uploads; scanned PDFs are detected
and routed to a configured OCR engine. Individual entities can be preserved,
redacted, or retyped in the review UI, and PDFs can be exported with true
blackout redaction. All processing is in memory — nothing is persisted.

## Quick start

```bash
cp .env.example backend/.env     # then edit — every variable is documented there
docker compose up -d --build     # → http://localhost:8080
```

The stack runs in production mode by default (docs disabled, unsafe
configurations refuse to start). The backend has no published port, a read-only
filesystem, and no volumes.

Local development:

```bash
uv sync && npm install
uv run uvicorn backend.src.main:app --reload --host 0.0.0.0 --port 8000
npm run dev                      # → http://localhost:5173
```

See [Installation](https://katherlab.github.io/deidentifier/getting-started/installation/)
and [Configuration](https://katherlab.github.io/deidentifier/operations/configuration/).

## Tests and checks

```bash
uv run ruff check backend/ && uv run ruff format --check backend/
uv run pytest
npm run check && npm test && npm run build
npm run test:e2e                 # Playwright smoke against a fake LLM
```

CI workflows exist but are `workflow_dispatch`-only while the repository is
private — run the commands above locally. See
[Contributing](https://katherlab.github.io/deidentifier/development/contributing/).

## Evaluation

A standalone harness scores the pipeline against annotated ground truth,
reporting document-level leakage alongside character- and span-level metrics:

```bash
uv run python -m backend.src.evaluation.run \
    --input annotations.jsonl --output evaluation-results.json --detectors rules,llm
```

See [Evaluation](https://katherlab.github.io/deidentifier/evaluation/).

## Privacy defaults

- All processing is in memory; nothing is persisted server-side.
- Logs never contain document content (enforced by a safe logger).
- API responses are sent with `Cache-Control: no-store`.
- No analytics, telemetry, CDN, or third-party fonts and scripts.
- All model and OCR backends are configurable base URLs, local by default; the
  UI shows a banner when a configured endpoint is not local.
- The repository contains only clearly marked synthetic example documents.

## Project documents

| File | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | The canonical codebase guide (architecture, conventions, pitfalls) |
| [`DESIGN_DOCUMENT.md`](DESIGN_DOCUMENT.md) | The v1 design and milestones |
| [`CHANGELOG.md`](CHANGELOG.md) | Release notes |
| [`.github/SECURITY.md`](.github/SECURITY.md) | Vulnerability disclosure policy |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | Bundled OSS components and licenses |
| [`CITATION.cff`](CITATION.cff) | Citation metadata |

## License

AGPL-3.0-or-later. See [`LICENSE`](LICENSE).
