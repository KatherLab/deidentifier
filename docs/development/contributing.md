# Contributing

## Setup

```bash
git clone https://github.com/KatherLab/deidentifier.git
cd deidentifier
uv sync
npm install
cp .env.example .env
```

Run it:

```bash
uv run uvicorn backend.src.main:app --reload --host 0.0.0.0 --port 8000
npm run dev        # → http://localhost:5173
```

## The gate before every commit

```bash
uv run ruff check backend/ && uv run ruff format --check backend/
uv run pytest
npm run check && npm test && npm run build
npm run test:e2e            # when you touched the API or the UI flow
```

!!! warning "CI does not run automatically right now"

    The repository is private, where Actions minutes are billed, so every
    workflow is `workflow_dispatch`-only. Nothing catches a broken commit for
    you — run the commands above locally. See
    [Developer guide](developer-guide.md#ci).

## Read this first

[`AGENTS.md`](https://github.com/KatherLab/deidentifier/blob/main/AGENTS.md) in
the repository root is the canonical guide to the codebase: architecture,
conventions, pitfalls, and the rules that are not negotiable. `CLAUDE.md` is a
stub that includes it.

The five principles it opens with are the ones a review will hold you to:

1. Immutable source, spans only.
2. Recall over precision.
3. Simple mode is the app, not a mode.
4. Configurable endpoints, local by default.
5. Never claim more than was checked.

## Conventions in brief

**Backend** — `snake_case` files/functions, `PascalCase` models. Domain logic
in `utils/`, external integrations in `services/` (with their own `*Error`
carrying a `status_code`). Every log call goes through
`get_safe_logger(__name__)`, and content is never interpolated into an event
string.

**Frontend** — `PascalCase.vue`, `<script setup lang="ts">`,
`defineProps<Props>()`. Components call `services/*Api.ts`, never the axios
instance. Build from `components/common/` primitives. Never write document
content to `localStorage`. Colour is never the only signal — every highlight
and badge carries a label.

**Tests** — new logic gets a unit test; a new route gets an integration test; a
new frontend helper gets a Vitest spec; a change to the user-visible workflow
gets an e2e assertion. Fixtures are **synthetic only**, marked
`SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION`.

**Docs** — a change to user-facing behaviour, configuration, or the workflow
updates the relevant page under `docs/`. A change to a documented screen means
re-running `npm run screenshots`.

**Changelog** — add an entry under `[Unreleased]` when the change affects users
or setup. Skip internal refactors, tests, and CI.

**Dependencies** — every dependency is pinned exactly (`==` in
`pyproject.toml`, a bare version in `package.json`), so the version an operator
runs is the version that was tested. Bumping one means editing the pin and
re-running `uv lock` / `npm install`, not widening the range. Dependabot
proposes the bumps weekly.

## Pull requests

- One topic per PR; keep the diff readable.
- Say what you ran from the gate above.
- Say which principle the change touches if it touches one.
- **Never attach a real document.** Reproduce with synthetic text.

## Reporting bugs

Include the version (`GET /api/v1/status`), the source type, the exact message,
the warning categories from expert mode, and the relevant log lines — which
contain no document content by design. Check any excerpt you paste anyway.

Security issues do not go in the issue tracker: see
[`.github/SECURITY.md`](https://github.com/KatherLab/deidentifier/blob/main/.github/SECURITY.md).

## License

AGPL-3.0-or-later. By contributing you agree your work is licensed under it.
Note that `pymupdf` is AGPL, which rules out any future relicense to a
permissive license.
