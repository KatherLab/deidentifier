# Troubleshooting

## Startup

### The backend container exits immediately

Read its log:

```bash
docker compose logs backend | tail -20
```

A message starting with `Refusing to start:` is production mode rejecting an
unsafe configuration. The three causes:

| Message | Fix |
|---|---|
| `the mock detector must not be enabled in production (DETECTORS)` | Remove `mock` from `DETECTORS`. |
| `APP_ALLOW_INSECURE_CONTENT_LOGGING must be false in production` | Set it to `false`. It allows document content in logs. |
| `detector 'llm' is enabled but OPENAI_API_BASE/LLM_MODEL are not set` | Configure both, or drop `llm` from `DETECTORS`. |

### The frontend loads but every request fails

- In Docker: nginx proxies `/api/` to the backend — check that the backend is
  healthy (`docker compose ps`).
- In local development: the frontend calls `http://localhost:8000` directly, so
  the backend must be on port 8000 and its `APP_CORS_ORIGINS` must include the
  dev server's origin.

## Warnings in the header

| Chip | Meaning |
|---|---|
| *Externer Endpunkt* | A configured endpoint is not loopback, not a private address, and not a single-label Docker service name. **Document content will leave this machine.** Verify it is intended. |
| *Detektor nicht bereit* | A detector is listed in `DETECTORS` but cannot run — usually `llm` without `OPENAI_API_BASE`/`LLM_MODEL`. Requests will fail rather than degrade. |

`GET /api/v1/status` returns the same information as JSON.

## Processing

### *Der KI-Erkennungsdienst ist nicht erreichbar*

The LLM endpoint is down, misconfigured, or blocked. Nothing partial is
returned — that is deliberate.

**Check `OPENAI_API_BASE` for `localhost` first.** In Docker that names the
backend container itself, not your machine, so a local Ollama or LM Studio is
unreachable no matter that it works in a browser on the host:

| The LLM runs… | Use |
|---|---|
| in the same compose project | `http://vllm:8000/v1` — the service name |
| on the Docker host | `http://host.docker.internal:11434/v1`, plus `extra_hosts: ["host.docker.internal:host-gateway"]` on the `backend` service (Linux) |
| on another machine | its hostname or IP |

Then verify the path from *inside* the container:

```bash
docker compose exec backend python -c \
  "import httpx,os; print(httpx.get(os.environ['OPENAI_API_BASE'].rstrip('/')+'/models', timeout=10).status_code)"
```

Also check that `OPENAI_API_BASE` includes the `/v1` suffix most servers
expect, and that `LLM_MODEL` names a model that server actually serves.

### *Dieses PDF scheint gescannt zu sein. OCR ist nicht aktiviert.*

`OCR_ENGINE=none`. See [OCR engines](ocr-engines.md).

### A PDF has text but the result is nonsense

The PDF has a broken text layer, so the probe skipped OCR. Switch on **OCR
erzwingen** in the advanced settings.

### *Ergebnis abgelaufen – wird neu berechnet*

The 15-minute in-memory detection cache expired. The app re-sends the source
text automatically; you only see the message if that retry also fails. Expected
behaviour, not a bug — nothing is persisted.

### Processing is slow

Roughly in order of impact:

| Dial | Effect |
|---|---|
| `LLM_DETECTION_PASSES=1` | Halves detection cost; slightly lower recall. |
| `LLM_RECHECK_ENABLED=false` | Saves one call per document; you lose the output audit. |
| `LLM_MAX_CONCURRENT_REQUESTS` | Raise it if the LLM server has headroom, lower it if it is overloaded. |
| `VISION_OCR_RENDER_SCALE` | Lower renders fewer pixels per page. |
| `LLM_CHUNK_CHARS` | Larger chunks mean fewer requests, if the model's context allows. |

A scanned PDF is dominated by OCR: one model call per page, capped by
`VISION_OCR_MAX_CONCURRENT_PAGES`.

### Uploads rejected as too large

`APP_MAX_UPLOAD_MB` (default 20). The check happens before buffering, so the
413 is immediate. Long scans legitimately exceed it.

## Results

### Names are not detected

Almost always: the `llm` detector is not enabled. `DETECTORS=rules` alone finds
only structured identifiers. Check `GET /api/v1/status`.

If the LLM *is* enabled and names are still missed, measure before tuning —
[Evaluation](../evaluation/index.md) — then consider more passes, a stronger
model, or a targeted extra instruction.

### The status is *Prüfbedarf* on every document

Usually correct rather than broken: the labelled-field check fires on anything
following `Patient:`/`Name:` that is not a placeholder, and preserved clinical
dates are found again by the rule re-detection. Read a few warnings before
changing anything — see [Warnings & validation](../user-guide/validation.md).

### The PDF export is refused

The verification step could not confirm that every redacted string is gone, so
the export failed closed instead of handing you a file that looks redacted. The
error names the reason. Reproduce with a synthetic document and report it.

### The redacted-PDF preview stays empty

The browser's built-in PDF viewer is unavailable or blocked. The download still
works; use *Als PDF* from the export menu.

## Reporting a problem

Include: the app version (shown at the bottom of every screen, also in
`GET /api/v1/status`), the source type
(`paste`/`txt`/`docx`/`pdf`/`pdf-ocr`), the exact message, the warning
categories from [expert mode](../user-guide/advanced-settings.md#expert-mode),
and the relevant backend log lines.

!!! danger "Never attach a real document"

    Reproduce with synthetic text — `backend/tests/files/` has examples — and
    attach that instead. Backend logs contain no document content by design;
    check any excerpt you paste anyway.
