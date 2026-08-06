# LLM endpoints

The prompted LLM is the **primary detector** for German clinical text. The rule
detector only covers structured identifiers; without an LLM, names in running
prose are not found.

## What the app expects

Any **OpenAI-compatible** `/chat/completions` endpoint. There is no
provider-specific code: vLLM, llama.cpp, Ollama, LM Studio, an in-house
gateway, or a hosted API all work.

```env
DETECTORS=rules,llm
OPENAI_API_BASE=http://vllm:8000/v1
OPENAI_API_KEY=              # often empty for local servers
LLM_MODEL=your-model-id
```

!!! warning "Not `localhost`, unless the backend runs on the host"

    In the Docker deployment the backend is a container, so
    `http://localhost:11434/v1` resolves to that container rather than to your
    machine. Use a compose service name (`http://vllm:8000/v1`) or
    `http://host.docker.internal:11434/v1` — the latter needs
    `extra_hosts: ["host.docker.internal:host-gateway"]` on the `backend`
    service on Linux. `localhost` is right only for the local development
    setup, where the backend runs directly on the host.

!!! danger "Document content goes to this endpoint"

    Every detection request sends document text there, and the re-check sends
    the anonymized output. Point it at a service inside your own network. The
    app compares the host against loopback, private ranges, and single-label
    Docker service names, and shows a header banner when it is none of those.

## How the app uses it

| Aspect | Behaviour |
|---|---|
| Structured output | `response_format: json_schema`, with a `guided_json` fallback for vLLM/llama.cpp-style servers. |
| Output shape | `{"entities": [{"text", "type", "role"}]}` — **strings, never offsets**. The app locates them in the source itself. |
| Chunking | Overlapping chunks (`LLM_CHUNK_CHARS` / `LLM_CHUNK_OVERLAP`), split at paragraph → line → sentence boundaries. |
| Passes | `LLM_DETECTION_PASSES` independent runs, unioned. Pass 1 at temperature 0; later passes sample slightly. |
| Truncation | A response cut off by the output limit is retried on halves of the chunk; below a floor it becomes a hard error. |
| Concurrency | `LLM_MAX_CONCURRENT_REQUESTS` caps passes × chunks × documents globally. |
| Injection | The document is fenced between `DOCUMENT START/END` markers and declared untrusted data whose embedded instructions must be ignored. |

## Choosing a model

Requirements, in priority order:

1. **Solid German.** The documents are German clinical prose with heavy
   abbreviation and inflection.
2. **Reliable JSON / structured output.** Malformed output costs a retry and
   ultimately fails the request.
3. **Verbatim copying.** The model must reproduce mentions character for
   character — the grounding step tolerates umlaut variants, hyphenation and
   whitespace differences, but not paraphrase.
4. **Context length** comfortably above `LLM_CHUNK_CHARS`.

Instruction-tuned mid-size open models served by vLLM are the sweet spot for a
hospital deployment. Do not take anyone's word for it, including this page:
score candidates on your own annotated documents with the
[evaluation harness](../evaluation/index.md) and compare **document-level
leakage** first.

## Self-hosting with vLLM

```bash
docker run --rm --gpus all -p 8000:8000 --ipc host \
  vllm/vllm-openai:latest --model <your-model> --host 0.0.0.0 --port 8000
```

```env
OPENAI_API_BASE=http://vllm:8000/v1
LLM_MODEL=<your-model>
```

Run that as a service in the same compose project and the service name is the
host — a single-label host, which counts as local and raises no banner. Started
standalone as above, it is reachable from the backend container at
`http://host.docker.internal:8000/v1` instead.

## Tuning

| Symptom | Try |
|---|---|
| Too slow | `LLM_DETECTION_PASSES=1`; raise `LLM_MAX_CONCURRENT_REQUESTS` if the server has headroom; consider `LLM_RECHECK_ENABLED=false` (you lose the audit). |
| Endpoint overloaded / rate-limited | Lower `LLM_MAX_CONCURRENT_REQUESTS`. It is a global cap, so this is the right dial for a shared server. |
| Timeouts on long documents | Raise `LLM_REQUEST_TIMEOUT_SECONDS`; lower `LLM_CHUNK_CHARS`. |
| Missed entities | `LLM_DETECTION_PASSES=3`; a stronger model; a targeted *Zusätzliche Anweisung* in the advanced settings. |
| Entities reported but not located | Warnings say so explicitly. Usually a model paraphrasing instead of copying — a model problem, not a configuration one. |

## Verifying

1. `GET /api/v1/status` → the `llm` detector must report `ready: true`.
2. Run a synthetic document through the UI and check that names are found.
3. Confirm the header shows no external-endpoint banner.

If the endpoint is unreachable, requests fail with *"Der KI-Erkennungsdienst
ist nicht erreichbar. Das Dokument wurde NICHT anonymisiert."* — a deliberate
hard failure, never a partial result.
