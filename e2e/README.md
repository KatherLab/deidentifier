# End-to-end harness

Two Playwright suites share one set of servers:

| Command              | Config                              | Suite               | Purpose                                            |
| -------------------- | ----------------------------------- | ------------------- | -------------------------------------------------- |
| `npm run test:e2e`   | `playwright.config.ts`              | `e2e/tests/`        | Smoke test of the whole product path               |
| `npm run screenshots`| `playwright.screenshots.config.ts`  | `e2e/screenshots/`  | Regenerates `docs/assets/screenshots/*.png`        |

Both boot:

1. **`e2e/support/fake-llm.mjs`** on `127.0.0.1:9099` — a deterministic
   OpenAI-compatible server (the Node counterpart of
   `backend/tests/fake_llm.py`). It scans the submitted chunk for the
   identifiers of the synthetic fixtures in `backend/tests/files` and reports
   the ones actually present, so grounding, chunking and the LLM re-check all
   run against real — but predictable — model output.
2. **The FastAPI backend** on `127.0.0.1:8000` with
   `ENV_PATH=backend/.env.e2e` (`DETECTORS=rules,llm`, OCR off, LLM pointed at
   the fake). `ENV_PATH` is always set explicitly so a developer's own
   `backend/.env` — which may point at real endpoints — can never be used by an
   automated run.
3. **The Vite dev server** on `3000` (smoke) or `3100` (screenshots).
   `frontend/services/api.ts` talks to `http://localhost:8000` directly in dev
   mode, so both origins are allow-listed in `backend/.env.e2e`.

   Locally the smoke suite *reuses* an existing server on its port
   (`reuseExistingServer: !CI`), which means an unrelated dev server on 3000
   gets tested instead — the symptom is every selector timing out at once. Run
   `E2E_PORT=3100 npm run test:e2e` to take the other port (3000 and 3100 are
   the CORS-allowed ones).

Nothing is persisted server-side, so there is no state to reset between runs.

Both configs pin the browser locale to `de-DE`. The UI language follows the
browser (German, English, French, Spanish — see `frontend/i18n`), and every
selector in these suites is written against the German labels; without the pin
a runner in an English locale would fail on every one of them. The one
exception is the language-switch spec, which switches to English on purpose.

## Adding fixtures

The fake model only reports mentions it knows. When you add a document to
`backend/tests/files` and want the LLM detector to find something in it, add
the literal mention strings to `KNOWN_MENTIONS` in
`e2e/support/fake-llm.mjs` — exactly as they appear in the document, the way a
real model is expected to copy them.

## Screenshots

`npm run screenshots` rewrites every image under `docs/assets/screenshots/`.
Re-run it after any UI change that affects a documented screen, and review the
diff before committing — these images ship in the public documentation site.

Two harness details worth knowing:

- The screenshot project runs with `channel: 'chromium'` (new headless). The
  default headless shell has no PDF viewer, so the redacted-PDF preview
  would be captured as a blank panel.
- Everything past the core path is wrapped in `capture()`, which logs
  `SKIPPED <name>` and continues. Check the run output: a silently missing
  image is a drifted selector, not an intentionally dropped screen.

Only synthetic fixtures may ever reach this harness. The images are published.
