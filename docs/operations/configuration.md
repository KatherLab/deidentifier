# Configuration

All configuration is environment variables. The authoritative reference is
[`.env.example`](https://github.com/KatherLab/deidentifier/blob/main/.env.example),
which documents every variable the application reads; this page groups them and
explains the consequences.

**Where they are read from**, in order: the `ENV_PATH` file if that variable is
set, otherwise `.env` in the repo root (the recommended location), otherwise
`backend/.env`. Actual environment variables always win.

The **Default** column below is the built-in default that applies when a
variable is absent — not necessarily what `.env.example` writes into a fresh
`.env`. Where the two differ, the table says so.

## Application

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` disables the API docs and refuses unsafe configurations. Set it for anything real. |
| `APP_MAX_UPLOAD_MB` | `20` | Rejected with 413 before the file is buffered. Scans are large; raise it if you process long ones. |
| `APP_MAX_TEXT_CHARS` | `500000` | Extracted-text limit. Guards against a pathological OCR result flooding the LLM. |
| `APP_ALLOW_INSECURE_CONTENT_LOGGING` | `false` | **Dev only.** Allows document content in logs, prints a loud startup warning, and is refused in production. |
| `APP_CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Only relevant for local development; in Docker the frontend proxies same-origin. |

## Deployment banner

A bar above the header for a deployment-wide notice — "Research Use Only!",
"Test system — do not use with patient data". The text is yours and is shown
verbatim in every interface language, so write it in the language your users
read (or keep it short and unambiguous).

| Variable | Default | Notes |
|---|---|---|
| `BANNER_ENABLED` | `false` | Turns the banner on. Enabled with an empty `BANNER_TEXT` shows nothing. |
| `BANNER_TEXT` | *(empty)* | The line to display, shown as written. |
| `BANNER_COLOR` | `amber` | `amber`, `red`, `blue`, `green` or `gray`. An unrecognized value falls back to `amber` rather than failing startup. |

```bash
BANNER_ENABLED=true
BANNER_TEXT='Research Use Only!'
BANNER_COLOR=amber
```

## Detectors

| Variable | Default | Notes |
|---|---|---|
| `DETECTORS` | `rules` | Comma-separated: `rules`, `llm`, `mock`, `privacy_filter`. `.env.example` ships `rules` so a fresh copy starts with no external services. **Recommended for real use: `rules,llm`.** |

A detector that is listed but cannot run makes the request fail with 503 rather
than returning a partial result. `mock` is for tests and offline development
and is refused in production. `privacy_filter` is not implemented yet.

## Detection LLM

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_BASE` | *(empty)* | Any OpenAI-compatible endpoint: Ollama, vLLM, LM Studio, a gateway. Include the `/v1` suffix most servers expect. |
| `OPENAI_API_KEY` | *(empty)* | Empty is fine for most local servers. |
| `LLM_MODEL` | *(empty)* | Required when `llm` is enabled. |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `120` | Per request. |
| `LLM_CHUNK_CHARS` | `16000` | Chunk size for long documents. Keep it well inside the model's context. |
| `LLM_CHUNK_OVERLAP` | `500` | Overlap so entities are not cut at a boundary. |
| `LLM_DETECTION_PASSES` | `2` | Independent passes whose results are unioned. Recall-first; doubles cost. `1` is faster, `3` catches a little more. |
| `LLM_MAX_CONCURRENT_REQUESTS` | `4` | **Total** in-flight requests across all documents. The main throughput/pressure dial. |
| `LLM_RECHECK_ENABLED` | `true` | The audit of the anonymized output. One extra call per document; produces warnings only. |

!!! warning "`localhost` means the container, not your machine"

    The backend runs in its own container, so `http://localhost:11434/v1`
    points at the backend itself and the request fails with *"Der
    KI-Erkennungsdienst ist nicht erreichbar"*. From a container, reach:

    | The LLM runs… | Use |
    |---|---|
    | as a service in the same compose project | `http://vllm:8000/v1` — the service name |
    | on the Docker host (a local Ollama, say) | `http://host.docker.internal:11434/v1` |
    | on another machine | its hostname or IP |

    On Linux, `host.docker.internal` resolves only if you add it to the
    `backend` service in `compose.yml`:

    ```yaml
    extra_hosts: ["host.docker.internal:host-gateway"]
    ```

    `localhost` is correct only when you run the backend directly on the host,
    as in the local development setup.

Details and model recommendations: [LLM endpoints](llm-endpoints.md).

## Extraction & OCR

| Variable | Default | Notes |
|---|---|---|
| `DOCLING_SERVE_URL` | *(empty)* | Optional, and empty by default — nothing is contacted. Unset or unreachable falls back to local pypdf extraction. |
| `DOCLING_MIN_EXTRACTED_CHARS_PDF` | `100` | Below this per page, a PDF counts as scanned. |
| `PDF_MAX_PAGES_FOR_TEXT_PROBE` | `5` | How many pages the probe samples. |
| `OCR_ENGINE` | `none` | `none`, `docling_tesseract`, `llm_vision`, `mistral_ocr` (not implemented). `none` rejects scanned PDFs with a clear message. |

Engine-specific variables (`MISTRAL_*`, `VISION_OCR_*`), including the
Unlimited-OCR recipe: [OCR engines](ocr-engines.md).

## Second-net detector

`PRIVACY_FILTER_ENABLED` / `PRIVACY_FILTER_BASE_URL` are placeholders for a
planned additional detector. Leave them off.

## Compose-level variables

Read from the same `.env` by `compose.yml` itself rather than by the
application, so they only apply to the Docker deployment.

| Variable | Default | Notes |
|---|---|---|
| `FRONTEND_PORT` | `8080` | The published port of the `frontend` container — the only published port of the stack. |
| `DEIDENTIFIER_IMAGE_TAG` | `latest` | Image tag for both services. Pin a release rather than tracking `latest`. |
| `APP_ENV` | `production` | `compose.yml` overrides the application default of `development`. |

## Changing configuration

```bash
$EDITOR .env
docker compose up -d          # recreates the backend with the new settings
```

Settings are read once at startup — there is no admin UI and no runtime
override, deliberately: the set of endpoints document content may reach is a
deployment decision, not a user decision.

## A safe starting point

```env
APP_ENV=production
DETECTORS=rules,llm
OPENAI_API_BASE=http://vllm:8000/v1
LLM_MODEL=your-model
OCR_ENGINE=none          # until you have an OCR endpoint you trust
```

Then verify in the UI: the header must show **no** external-endpoint warning,
and `GET /api/v1/status` must report every configured detector as `ready`.
