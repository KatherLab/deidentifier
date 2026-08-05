# Testing

Four suites, each answering a different question.

| Suite | Command | Question |
|---|---|---|
| pytest | `uv run pytest` | Does the pipeline behave correctly? |
| Vitest | `npm test` | Do the frontend helpers behave correctly? |
| Playwright smoke | `npm run test:e2e` | Does the whole product path work? |
| Screenshots | `npm run screenshots` | Do the documentation images still match the app? |

## Backend (pytest)

```bash
uv run pytest
uv run pytest --cov=backend/src --cov-report=term-missing
uv run pytest backend/tests/unit/test_grounding.py -v
```

Layout:

- **`tests/unit/`** — recognizers; grounding (multiple occurrences, not found,
  normalized fallback); chunk boundaries; overlap resolution; right-to-left
  application; consistent tags; override precedence; the source-unchanged
  invariant; safe-logger rejection; PDF export; vision OCR; evaluation metrics.
- **`tests/integration/`** — the API through FastAPI's `TestClient`, plus
  `test_llm_e2e.py` driving the full pipeline against `tests/fake_llm.py`, an
  in-process fake OpenAI-compatible server.
- **`tests/files/`** — fixtures. **Synthetic only**, each headed
  `SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION`.

`conftest.py` sets `ENV_PATH` to a nonexistent file **before importing any
backend module**, so a developer's `backend/.env` — which may point at real
endpoints — can never be picked up by a test run. Preserve that when you add
fixtures.

### What deserves a test

The invariants, above all: the source text is never modified; every span
verifies against the source; a right-to-left application keeps earlier offsets
valid; an enabled-but-unavailable detector fails the request; the safe logger
drops content fields; an unverifiable export is refused.

Umlauts, ß, combining characters, and non-breaking spaces belong in any test
that touches offsets — they are where offset bugs actually live.

## Frontend (Vitest + jsdom)

```bash
npm test
npm run test:watch
```

Specs sit next to the code they cover as `*.test.ts`, under `frontend/utils/`,
`frontend/composables/`, `frontend/services/`, `frontend/stores/`. Config is
`vitest.config.ts` at the repository root, kept separate from
`frontend/vite.config.ts` so the test toolchain never reaches the production
bundle. Specs import from `vitest` explicitly — there are no ambient globals.

Current coverage is the pure helpers (`textSegments`, `policy`, `errors`,
`entityLabels`), the composables, the API-payload helpers, and the settings
store. Component-level coverage is not set up.

Two specs are load-bearing rather than routine: `policy.test.ts` pins the
frontend mirror of the backend default policy, and `textSegments.test.ts`
pins code-point-correct segmentation.

## End to end (Playwright)

```bash
npm run test:e2e
npm run test:e2e:ui     # interactive
```

The harness boots a deterministic fake OpenAI-compatible server
(`e2e/support/fake-llm.mjs`), the real backend with `ENV_PATH=backend/.env.e2e`
(`DETECTORS=rules,llm`), and the Vite dev server. Only the model is faked, so
grounding, chunking, and the re-check run for real. Nothing is persisted, so
there is no state to reset between runs.

`e2e/tests/workflow.spec.ts` covers: pasted text → detection → override →
undo; the export menu and a text download; a PDF upload → redacted-PDF preview
→ PDF export; rejection of an unsupported file; and the status header.

Details, including how to teach the fake model about a new fixture, are in
[`e2e/README.md`](https://github.com/KatherLab/deidentifier/blob/main/e2e/README.md).

## Documentation screenshots

```bash
npm run screenshots
```

Walks the same path with a fixed viewport, retina scale, and light theme, and
rewrites every PNG under `docs/assets/screenshots/`. Re-run it after any UI
change that affects a documented screen, and review the image diff before
committing — these ship in the public docs.

Captures past the core path are wrapped in a helper that logs
`SKIPPED <name>` and continues, so one drifted selector costs one image rather
than the run. **Read the output**: a missing image is a bug, not a decision.

The screenshot project runs with `channel: 'chromium'` because the default
headless shell has no PDF viewer and would capture the redacted-PDF panel
blank.

## Evaluation is not a test

[Evaluation](../evaluation/index.md) measures anonymization quality on
annotated documents. It is not part of CI and never will be: it needs real
annotated data, which does not belong in this repository. Run it deliberately,
record the numbers, and cite them when someone asks how well the tool works.
