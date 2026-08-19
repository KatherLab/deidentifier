# Security overview

This page describes the security posture of the application. For reporting a
vulnerability, see
[`.github/SECURITY.md`](https://github.com/KatherLab/deidentifier/blob/main/.github/SECURITY.md).

!!! warning "Research and evaluation use"

    This is an internal evaluation tool, **not a certified medical device** and
    **not a guarantee of legal anonymization**. The deploying institution is
    the data controller and is responsible for its own security review, DPIA,
    and information-governance sign-off before processing patient data.

## Design decisions that carry the weight

| Decision | Consequence |
|---|---|
| **No persistence.** No database, no object storage, no volumes; the backend container runs read-only. | There is no data at rest to protect, breach, or subpoena. A restart drops everything. |
| **No authentication by default.** The app is deployed behind the institution's auth proxy; optionally it can require an [OIDC sign-in](operations/sso.md) itself. | One fewer credential store and session mechanism to secure — and a hard requirement that the proxy (or the gate) is actually there. The gate holds no accounts and no passwords: the session is a signed cookie, the provider owns the identity. |
| **Content-refusing logger.** Fields whose names carry document content are dropped before a log line is written. | Logs can be shipped to normal infrastructure without becoming a PHI store. |
| **Configured endpoints only.** Model and OCR base URLs are deployment configuration, not user input. | The set of destinations document content may reach is fixed at deploy time and visible in the UI. |
| **Fail closed.** An unavailable detector fails the request; an unverifiable PDF export is refused. | The system never reports a document as processed when it was not fully checked. |

## Attack surface

Four endpoints under `/api/v1` plus two health endpoints — see
[Data flow](DATA_FLOW.md). There are no accounts, no stored documents, no
admin surface, and no user-supplied endpoint URLs.

The realistic threats are the ones inherent to the job: document content in
transit to a model endpoint, prompt injection from within a document, and
output that looks anonymized but is not. Each is covered in the
[Threat model](THREAT_MODEL.md).

## Controls

**Transport and headers.** `SecurityHeadersMiddleware` sets X-Frame-Options,
a Content-Security-Policy, Referrer-Policy, and `Cache-Control: no-store` on
content responses. TLS is terminated by your proxy.

**Input validation.** Extension allow-list (`.txt`, `.docx`, `.pdf`), a size
cap enforced before buffering (413), an extracted-text cap, and typed Pydantic
request models. Malformed, password-protected, or unsupported files produce
clear errors rather than stack traces.

**Outbound requests.** All clients disable redirect following, set explicit
timeouts, and sanitize errors — an upstream error is never echoed to the
client verbatim. Endpoint URLs come from configuration, never from a request,
so there is no SSRF vector through user input.

**Prompt injection.** Document content is fenced between explicit
`DOCUMENT START/END` markers, and the system prompt declares it untrusted data
whose embedded instructions must be ignored — including claims that the
document is already anonymized. The model's output is *only* a list of strings,
which deterministic code then locates in the source: a model that "obeys" an
injected instruction can cause a missed entity, but it cannot cause an edit,
an exfiltration, or a code path change. The independent leakage validation is
the backstop.

**Supply chain.** Dependencies are pinned via `uv.lock` and
`package-lock.json`, updated weekly by Dependabot, and scanned by the
`security.yml` workflow (CodeQL, `pip-audit`, `npm audit`, Trivy, license
check). Images are built from those lockfiles and run as non-root.

**No third-party runtime dependencies.** No analytics, no telemetry, no CDN,
no external fonts or scripts. The app needs no internet access at runtime.

## Deployment checklist

- [ ] An authenticating reverse proxy is in front of the frontend, and port
      8080 is not reachable around it — or `OIDC_ENABLED=true` with the
      provider configured ([Single sign-on](operations/sso.md)).
- [ ] TLS terminates at that proxy. With the OIDC gate on, `APP_PUBLIC_URL`
      is an `https://` URL, so the session cookie is `Secure` (the backend
      warns at startup when it is not).
- [ ] `APP_ENV=production`.
- [ ] `APP_ALLOW_INSECURE_CONTENT_LOGGING=false` (production refuses otherwise).
- [ ] `DETECTORS` contains no `mock` (production refuses otherwise).
- [ ] Every configured endpoint is inside your network — the UI shows **no**
      external-endpoint banner.
- [ ] The backend publishes no port and mounts no volumes (the shipped
      `compose.yml` default).
- [ ] Log shipping has been checked against a real run: no document content.
- [ ] Users have been told, in writing, that the output requires human review.
- [ ] The pipeline has been evaluated on your document types
      ([Evaluation](evaluation/index.md)).

## Known limitations

- **Anonymization is best-effort.** No detector finds everything. Human review
  is part of the design, not a disclaimer.
- **Indirect identification is not solved.** Preserved dates, rare diagnoses,
  professions and places can identify a person in combination. The LLM
  re-check flags this qualitatively; it does not measure it.
- **OCR quality is a privacy control.** A misrecognized name is invisible to
  every downstream detector. See [OCR engines](operations/ocr-engines.md).
- **Filenames are not anonymized.** The *keep original filenames* export option
  is off by default for that reason.
- **The detection cache holds document text in process memory** for up to 15
  minutes. It is bounded and never written to disk, but it is not zeroed on
  eviction.
