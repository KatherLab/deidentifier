# Installation

Two ways to run the app: **Docker Compose** (what you deploy) and a **local dev
setup** (what you develop against). Both read configuration from `.env` in the
repo root.

## Docker Compose

Prerequisites: Docker (or Podman) with the Compose plugin. No GPU is needed
unless you run the OCR sidecar.

```bash
git clone https://github.com/KatherLab/deidentifier.git
cd deidentifier
cp .env.example .env
$EDITOR .env                     # fill in the LLM block at the top
docker compose up -d --build
```

The app is at **<http://localhost:8080>**.

The one thing to configure is at the top of `.env`: the detection LLM. Point
`OPENAI_API_BASE` at any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio,
a gateway) and set `LLM_MODEL` to a model it serves — see
[LLM endpoints](../operations/llm-endpoints.md) for model recommendations.
While those values are empty the backend refuses to start, and its log says
exactly that (`Refusing to start: detector 'llm' is enabled but
OPENAI_API_BASE/LLM_MODEL are not set`) — a deployment that silently misses
names would be worse. To look around without an LLM endpoint, set
`DETECTORS=rules`: the app then runs with no external services but finds only
structured identifiers, not names.

!!! warning "`localhost` in `.env` means the backend container"

    The most common first failure. A model server running on your machine is
    *not* at `localhost` from inside the container — use
    `host.docker.internal` or a compose service name. See
    [Configuration](../operations/configuration.md#detection-llm).

What that starts:

| Container | Role |
|---|---|
| `frontend` | nginx serving the SPA and reverse-proxying `/api/` to the backend. The only published port (`8080`). |
| `backend` | FastAPI. **No published port**, read-only filesystem, no volumes — nothing is persisted. |

`APP_ENV` defaults to `production` in `compose.yml`, which disables the API
docs and refuses to start on unsafe configuration (mock detector enabled,
insecure content logging enabled, or the `llm` detector enabled without an
endpoint). If the backend container exits immediately, read its log: the
message starts with `Refusing to start:`.

### Layered variants

```bash
# Development: source mounts + hot reload, backend exposed on :8000
docker compose -f compose.yml -f compose.dev.yml up --build

# Add a GPU OCR sidecar (vLLM) and wire it up — pick one:
docker compose -f compose.yml -f compose.unlimited-ocr.yml up -d   # baidu/Unlimited-OCR
docker compose -f compose.yml -f compose.chandra.yml up -d         # datalab chandra
```

The OCR overlays require an NVIDIA GPU and the NVIDIA Container Toolkit. Each
sets `OCR_ENGINE=llm_vision` and points the backend at its sidecar
automatically — see [OCR engines](../operations/ocr-engines.md).

### Behind a reverse proxy

The app has **no authentication by default**: it is designed to sit behind the
institution's existing auth proxy. Put your proxy in front of the `frontend`
container, terminate TLS there, and do not publish port 8080 beyond it.
`FRONTEND_PORT` changes the published port.

If you have no such proxy, the app can require a sign-in at your organisation's
OpenID Connect provider instead — see
[Single sign-on](../operations/sso.md). You still need TLS in front of it.

## Local development setup

Prerequisites: Python 3.13 or 3.14 (`requires-python = ">=3.13,<3.15"`),
[uv](https://docs.astral.sh/uv/), Node.js 24+.

```bash
uv sync
npm install
cp .env.example .env             # fill in the LLM block, as above
```

(Development mode starts with the LLM block empty, but every request then
fails with a clear 503 instead of a result.)

Two terminals:

```bash
uv run uvicorn backend.src.main:app --reload --host 0.0.0.0 --port 8000
npm run dev        # → http://localhost:5173
```

The dev frontend talks to `http://localhost:8000` directly, so that origin must
be listed in `APP_CORS_ORIGINS` (the shipped default covers ports 3000 and
5173).

Verify the install:

```bash
uv run pytest
npm test && npm run build
```

## Upgrading

```bash
git pull
docker compose up -d --build
```

There is no database and no migrations, so an upgrade is a rebuild. Check
[`CHANGELOG.md`](https://github.com/KatherLab/deidentifier/blob/main/CHANGELOG.md)
for configuration changes and compare your `.env` against the current
`.env.example` — new variables always have safe defaults, but defaults change.

In-flight results live in memory only: restarting the backend drops any cached
detection, and users with an open result get a "please re-run" message rather
than a broken page.
