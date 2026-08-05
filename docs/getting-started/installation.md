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
cp .env.example .env    # then edit it — see Configuration
docker compose up -d --build
```

The app is at **<http://localhost:8080>**.

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

# Add a GPU OCR sidecar (baidu/Unlimited-OCR via vLLM) and wire it up
docker compose -f compose.yml -f compose.unlimited-ocr.yml up -d
```

The `unlimited-ocr` overlay requires an NVIDIA GPU and the NVIDIA Container
Toolkit. It sets `OCR_ENGINE=llm_vision` and points the backend at the sidecar
automatically — see [OCR engines](../operations/ocr-engines.md).

### Behind a reverse proxy

The app has **no authentication**: it is designed to sit behind the
institution's existing auth proxy. Put your proxy in front of the `frontend`
container, terminate TLS there, and do not publish port 8080 beyond it.
`FRONTEND_PORT` changes the published port.

## Local development setup

Prerequisites: Python 3.13+, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
uv sync
npm install
cp .env.example .env
```

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
