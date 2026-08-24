# Risk register

A living list of known risks, their controls, and what remains. It is a
starting point for your own register, not a substitute for one — the residual
ratings assume the deployment described in [Deployment](operations/deployment.md).

Scale: likelihood and impact as low / medium / high; residual risk after the
listed controls.

## Privacy

| # | Risk | Controls | Residual | Owner |
|---|---|---|---|---|
| P1 | An identifier is missed and the output is used as if anonymized | Recall-first defaults, rule + LLM detection, multi-pass, independent leakage validation, visible status, mandatory human review, evaluation harness | **Medium** — inherent to the task | Deploying institution |
| P2 | Document content is sent to an endpoint outside the institution | Endpoints are deployment config; locality reported by `/api/v1/status`; persistent UI banner; deployment checklist | **Low**, if the checklist is followed; **high** if it is not | Operator |
| P3 | Preserved quasi-identifiers allow re-identification (dates, professions, rare diagnoses, places) | `OTHER_DATE` preservation is documented and configurable; the LLM re-check reports an indirect-identification concern | **Medium** — not measurable by the harness | Data controller |
| P4 | Poor OCR hides identifiers from every detector | Recognition-error warning on every OCR result; `ocr_quality` concern from the LLM audit; forced-OCR option; engine guidance | **Medium** | Operator + user |
| P5 | Exported filenames contain identifiers | Renaming is the default; the opt-in warns inline | **Low** | User |
| P6 | Document content reaches the logs | Content-refusing structured logger; unit test; production refuses the escape hatch | **Low** | Developers |
| P7 | Text in the detection cache outlives the request | 15-minute TTL, 100-entry bound, process memory only, cleared on restart | **Low** | — |

## Security

| # | Risk | Controls | Residual | Owner |
|---|---|---|---|---|
| S1 | The app is exposed without the auth proxy | Backend publishes no port; checklist; docs state the requirement repeatedly; optional built-in OIDC gate (`OIDC_ENABLED`) for deployments with no proxy, which refuses to start half-configured | **Low**, if reviewed at deployment | Operator |
| S2 | Prompt injection from document content | Fenced document markers, untrusted-data system prompt, strings-only model output, deterministic grounding, independent validation | **Low** for integrity; contributes to P1 | Developers |
| S3 | Parser vulnerability in a document library | Extension allow-list, size caps, read-only non-root container, no persistence, Dependabot + CI scanning | **Low** | Developers |
| S4 | A redacted PDF that is not actually redacted | Text removal + box coverage, post-export verification, fail-closed refusal, reconstruction for scans. The single overridable finding is one the anonymized text carries too, is named to the reviewer, and stays on screen after the export | **Low** | Developers |
| S5 | Dependency compromise | Pinned lockfiles, weekly updates, CodeQL/pip-audit/npm audit/Trivy | **Medium** — CI is currently manual-trigger only | Developers |
| S6 | A leaked request id lets someone re-run a cached document | Unguessable ids, 15-minute TTL, no listing endpoint, authenticated callers | **Low** | — |

## Operational

| # | Risk | Controls | Residual | Owner |
|---|---|---|---|---|
| O1 | The LLM endpoint is unavailable and users are blocked | Hard failure with an explicit "NOT anonymized" message rather than a partial result | **Low** — availability traded for safety, deliberately | Operator |
| O2 | An unsafe configuration reaches production | `validate_production_settings()` refuses to start; the reason is logged | **Low** | Operator |
| O3 | An upgrade changes behaviour silently | `CHANGELOG.md`, `.env.example` diff, no migrations to go wrong | **Low** | Operator |
| O4 | Users treat the tool as a guarantee | Warning on the input screen, in the README, and on every docs entry point; validation status is prominent | **Medium** — a training and governance problem | Data controller |

## Review

Revisit when: an endpoint changes, a detector or model changes, a new document
type is introduced, a dependency advisory lands, or at least annually. Record
evaluation results ([Evaluation](evaluation/index.md)) against P1 — it is the
only entry here with a number attached to it.
