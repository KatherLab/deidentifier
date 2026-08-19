# Deployment

## The stack

```bash
docker compose up -d --build     # → http://localhost:8080
```

| Service | Image | Notes |
|---|---|---|
| `frontend` | `ghcr.io/katherlab/deidentifier-frontend` | nginx (unprivileged) serving the SPA and proxying `/api/` to the backend. The only published port. |
| `backend` | `ghcr.io/katherlab/deidentifier-backend` | FastAPI. No published port, read-only root filesystem, `tmpfs` for `/tmp`, no volumes. |

Both run as non-root. `DEIDENTIFIER_IMAGE_TAG` pins a version;
`FRONTEND_PORT` changes the published port.

`--build` builds both images from the checkout, which is what you want while
the repository is private and the publish workflow is manual. Once a release
has been published to `ghcr.io`, a deployment host can skip the build
toolchain entirely:

```bash
DEIDENTIFIER_IMAGE_TAG=v0.2.1 docker compose pull
DEIDENTIFIER_IMAGE_TAG=v0.2.1 docker compose up -d
```

You still need `compose.yml` and your `.env` on that host.

nginx re-resolves the backend hostname per request, so recreating the backend
container does not require restarting the frontend.

## Production mode

`compose.yml` sets `APP_ENV=production` by default, which:

- disables `/docs` and `/openapi.json`,
- **refuses to start** when the mock detector is enabled, when
  `APP_ALLOW_INSECURE_CONTENT_LOGGING` is true, or when the `llm` detector is
  enabled without `OPENAI_API_BASE`/`LLM_MODEL`.

A backend that exits immediately after `docker compose up` almost always logs
`Refusing to start: …` with the exact reason.

## Authentication

None by default, by design: the app is meant to run behind the institution's
existing authenticating reverse proxy. Terminate TLS there, enforce
authentication and authorization there, and do not expose port 8080 beyond it.

Everything a user can reach is a stateless endpoint that processes the document
they submitted — there are no accounts, no stored documents, and nothing to
enumerate. That is only true as long as the proxy is actually in front of it.

Where that proxy does not exist, the app can require a sign-in at your
organisation's OpenID Connect provider itself — one setting plus the client
credentials, no accounts and no roles. See
[Single sign-on](sso.md). It replaces the *authentication* the proxy would
provide, not the TLS termination.

## Configuration

Read from `.env` in the repo root at runtime, never baked into an image:

```bash
cp .env.example .env
$EDITOR .env
docker compose up -d
```

`backend/.env` is still read as a fallback, with `.env` and the container
environment taking precedence. See [Configuration](configuration.md).

## Layered compose files

```bash
# Development: source mounts + reload, backend published on :8000
docker compose -f compose.yml -f compose.dev.yml up --build

# GPU OCR sidecar (vLLM), wired up automatically — pick one:
docker compose -f compose.yml -f compose.unlimited-ocr.yml up -d   # baidu/Unlimited-OCR
docker compose -f compose.yml -f compose.chandra.yml up -d         # datalab chandra
```

## Health and monitoring

| Endpoint | Purpose |
|---|---|
| `GET /health/live` | Process is up. Used by the container healthcheck. |
| `GET /health/ready` | Every detector in `DETECTORS` is *configured* well enough to run. |
| `GET /api/v1/status` | Detectors, OCR engine, endpoint hosts and their locality, limits. |

!!! note "Readiness is a configuration check, not a reachability check"

    `/health/ready` reports `degraded` when a detector is listed but
    unconfigured — `llm` without `OPENAI_API_BASE`/`LLM_MODEL`, for instance.
    It does **not** contact the LLM or OCR endpoints, so it stays `ready`
    against a configured-but-dead endpoint. Monitor those endpoints
    themselves; the app deliberately makes no network calls at startup or on
    a health probe.

`/api/v1/status` deliberately returns **hosts, not URLs**, and never keys or
paths — it is what the frontend uses to raise the "content leaves this machine"
banner, so it must stay safe to expose.

Logs go to stdout in the usual container fashion. They contain request ids,
timings, character counts, entity counts, and validation status — **never
document content**. Do not enable `APP_ALLOW_INSECURE_CONTENT_LOGGING` on a
system that processes real data; production mode refuses to start with it.

## Upgrading

```bash
git pull
docker compose up -d --build
```

No database, no migrations. Check `CHANGELOG.md` for configuration changes and
diff your `.env` against `.env.example`. Restarting drops in-flight
results: users with an open result see a "please re-run" message.

## Backup

There is nothing to back up except your configuration — that is the design.
Keep your `.env` in your usual secret store; everything else is in the
repository.
