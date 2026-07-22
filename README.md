# Medical Document Anonymizer

A locally deployable web app that anonymizes German clinical documents:
drop a document (or paste text), click one button, get anonymized text out —
with a review view showing exactly what was redacted and why.

> **This is an internal evaluation tool.** Its output does **not** establish
> legal anonymization. Results must be reviewed by a human, and anonymization
> quality must be validated locally before any downstream use.

See `DESIGN_DOCUMENT.md` for the architecture and roadmap.

## How it works

No generative model ever rewrites the document. Detectors (rules, and in
Milestone 2 a prompted LLM) only *propose* character spans; deterministic code
applies the replacements on the immutable source text, and an independent
leakage-validation pass re-scans the output and reports a
`PASS / REVIEW_REQUIRED / FAIL` status.

```text
Document → extraction → rule + LLM detection → span merging
        → deterministic transformation → leakage validation → review UI
```

Current milestone (2): pasted text plus `.txt`, `.docx` and `.pdf` uploads
(scanned PDFs are detected and routed to docling-serve/Tesseract OCR when
configured), rule-based German recognizers, and the **LLM detector** — a
prompted model behind any OpenAI-compatible endpoint that returns entity
strings as JSON, deterministically grounded to character offsets. Individual
entities can be preserved/redacted/retyped in the review UI; re-runs reuse
cached detection results. Remaining for Milestone 3: mistral_ocr and
llm_vision OCR engines, the privacy-filter second net, the evaluation
harness, and Docker packaging.

## Development setup

Backend (Python 3.13+, [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run uvicorn backend.src.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend (Vue 3 + Vite):

```bash
npm install
npm run dev        # http://localhost:5173
```

Tests and checks:

```bash
uv run pytest
uv run ruff check backend/ && uv run ruff format --check backend/
npm run check && npm run build
```

## Configuration

Copy `.env.example` to `backend/.env` and adjust. Every variable is documented
there. Key points:

- `DETECTORS` — comma-separated detector list (`rules`, `llm`, `mock`, …).
  The `mock` detector is for tests only; production mode refuses to start
  with it enabled.
- All model/OCR backends are configurable base URLs (OpenAI-compatible LLM,
  docling-serve, Mistral-OCR-compatible API, vision LLM). Local by default;
  the UI shows a banner when a configured endpoint is not local.

## Privacy defaults

- All processing is in memory; nothing is persisted server-side.
- Logs never contain document content (enforced by a safe logger).
- API responses are sent with `Cache-Control: no-store`.
- The repository contains only clearly marked synthetic example documents.
