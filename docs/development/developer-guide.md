# Developer guide

Day-to-day work in this repository. Architecture is in
[Architecture](architecture.md); the exhaustive conventions live in
[`AGENTS.md`](https://github.com/KatherLab/deidentifier/blob/main/AGENTS.md).

## Commands

```bash
# Backend
uv run uvicorn backend.src.main:app --reload --host 0.0.0.0 --port 8000
uv run ruff check backend/ && uv run ruff format backend/
uv run pytest

# Frontend
npm run dev
npm run check        # prettier + eslint + vue-tsc
npm test             # vitest
npm run build

# End to end
npm run test:e2e
npm run screenshots

# Docs
uv run --only-group docs mkdocs serve
```

## Adding a feature

1. **Schema** — `schemas/entities.py` for domain vocabulary,
   `schemas/anonymize.py` for the request/response contract.
2. **Domain logic** — a module under `utils/`, pure where possible. An
   external call belongs in `services/` with its own `*Error` carrying a
   `status_code`.
3. **Endpoint** — a module under `routers/v1/endpoints/`, registered in
   `routers/v1/api.py`.
4. **Config** — a field on `Settings` plus a documented block in
   `.env.example` (and a row in
   [Configuration](../operations/configuration.md) if users need it).
5. **Frontend** — mirror the type in `frontend/types/anonymizer.ts`, add the
   call to a `services/*Api.ts` module, put state on the active document in
   `stores/session.ts`, build the UI from `components/common/`.
6. **Tests** — unit for the logic, integration for the route, Vitest for a new
   frontend helper, e2e if the user-visible workflow changed.
7. **Docs + changelog** — the affected page, plus `CHANGELOG.md` when it
   affects users or setup. Re-run `npm run screenshots` for a documented screen.

## Adding a detector

Implement the `SpanDetector` protocol — `name`, `version`,
`async detect(text) -> DetectionOutcome` — then:

- register it in `build_detectors()` and teach `detector_ready()` what
  "configured" means for it,
- **raise `DetectorError` when it is enabled but cannot run.** Never return
  fewer spans instead: a document that was not fully checked must not look
  like one that passed,
- return spans whose `text` matches the source exactly; `validate_spans()`
  will reject anything else and warn,
- if it produces mention strings rather than offsets, route them through
  `utils/grounding.py` instead of writing new locating logic,
- add it to `DETECTORS` in `.env.example` and to
  [Configuration](../operations/configuration.md).

## Adding an OCR engine

Add a service class in `services/` with its own `*Result` and `*Error`, then a
branch in `extract_pdf()`. Requirements:

- **fail closed** — a page that cannot be transcribed fails the document
  rather than yielding a partial transcript,
- return `source_type="pdf-ocr"` and a recognition-error warning,
- emit `LayoutLine` entries if you can: they are what makes the reconstructed
  redacted PDF possible,
- respect a global concurrency cap via `utils/concurrency.py`,
- document it in [OCR engines](../operations/ocr-engines.md).

## Things that will bite you

**Offsets.** Backend offsets are Unicode code points. Frontend code that maps
offsets to DOM text must go through `Array.from()` like
`utils/textSegments.ts` — `String.prototype.slice` silently breaks on astral
characters.

**Policy drift.** `frontend/utils/policy.ts` mirrors the backend
`DEFAULT_POLICY`. Only deviations are sent, so a drifted mirror sends *nothing*
and displays a transformation the backend never applied. A Vitest spec pins
the key defaults; update both sides together.

**Logging.** `get_safe_logger(__name__)`, always. The filter works on field
*names*: `logger.info("done", chars=len(text))` is right,
`logger.info(f"text: {text}")` defeats it entirely.

**The cache is not persistence.** A 410 is normal and handled. Do not extend
the TTL indefinitely or write it to disk to "fix" it.

**Fixtures.** Synthetic only, marked as such. They end up in the repository,
in test output, and — via the screenshot harness — in the public docs site.

## Configuration in tests

`backend/tests/conftest.py` sets `ENV_PATH` to a nonexistent file **before any
backend import**, so a developer's `backend/.env` can never leak into a test
run. Keep that invariant when you add fixtures. The Playwright harness does the
same with an explicit `ENV_PATH=backend/.env.e2e`.

`get_settings()` is `lru_cache`d — clear it (`get_settings.cache_clear()`) when
a test needs different settings.

## CI

`.github/workflows/` holds `tests.yml`, `docs.yml`, `security.yml`, and
`docker-publish.yml`. **All four are `workflow_dispatch`-only**: the repository
is private and Actions minutes are billed. The real `push`/`pull_request`
triggers sit commented out at the top of each file, ready to be uncommented
when the repository goes public.

Practical consequence: nothing gates your commit. Run the full local gate from
[Contributing](contributing.md), and trigger the workflows manually from the
Actions tab before a release.

Dependabot (`.github/dependabot.yml`) is active — it does not consume Actions
minutes.

## Releasing

1. Bump the version in `package.json`, `pyproject.toml`, `CITATION.cff`, and
   the `APP_VERSION` default in `core/config.py` (it is what
   `/api/v1/status` reports).
2. `uv lock` if dependencies changed.
3. Move the `[Unreleased]` entries in `CHANGELOG.md` into a dated section.
4. Run the full local gate, plus `npm run test:e2e`.
5. Tag: `git tag v0.2.0 && git push origin v0.2.0`. Publishing a release is
   what triggers `docker-publish.yml` — which currently needs a manual run.
