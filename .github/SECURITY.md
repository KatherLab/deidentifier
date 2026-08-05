# Security Policy

Thanks for helping keep this project and its users safe. This document covers
how to report a vulnerability. For the security posture of the application
itself — threat model, data flow, deployment checklist — see
[`docs/SECURITY.md`](../docs/SECURITY.md) and the companion documents in
[`docs/`](../docs).

> ⚠️ **Evaluation tool.** This is an internal evaluation tool. It is **not a
> certified medical device**, and its output does **not** establish legal
> anonymization. The deploying institution is the data controller and is
> responsible for its own security review, DPIA, and information-governance
> sign-off before processing real patient data.

## Supported versions

This is an actively developed research project. Only the **latest release** and
the `main` branch receive security fixes. Please upgrade before reporting, in
case the issue has already been addressed.

| Version        | Supported          |
| -------------- | ------------------ |
| Latest release | :white_check_mark: |
| `main`         | :white_check_mark: |
| Older releases | :x:                |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report privately through either channel:

1. **GitHub Security Advisories (preferred)** — use the
   [**Report a vulnerability**](https://github.com/KatherLab/deidentifier/security/advisories/new)
   button on the repository's *Security* tab. This keeps the report private and
   lets us collaborate on a fix.
2. **Email** — contact the maintainer at **fabian.wolf2@tu-dresden.de** with
   the subject line `[deidentifier security]`.

Please include, where possible:

- a description of the vulnerability and its impact,
- steps to reproduce (proof of concept, affected endpoint, configuration),
- the version or commit hash and the deployment mode (detectors enabled, OCR
  engine, Docker or local),
- any suggested remediation.

> 🚫 **Never attach a real clinical document.** Reproduce with synthetic text —
> `backend/tests/files/` contains examples — and attach that instead.

## Anonymization failures

A missed identifier is a **known limitation**, not a vulnerability: no detector
finds everything, which is why human review is part of the design. Report those
as normal issues (with synthetic reproduction), or better, quantify them with
the [evaluation harness](../docs/evaluation/index.md).

Do report as a security issue anything that makes the tool *claim* more than it
checked, for example:

- a redacted PDF export whose blackout can be reversed or whose text remains
  extractable,
- document content appearing in logs or in an API response that should not
  carry it,
- a status of `PASS` while redacted content demonstrably remains in the output,
- a path by which one user could reach another user's document or result.

## What to expect

- **Acknowledgement:** we aim to confirm receipt within **5 business days**.
- **Assessment:** we investigate and keep you updated on findings and planned
  remediation.
- **Disclosure:** we follow **coordinated disclosure**. Please allow a
  reasonable window for a fix before public disclosure. We are happy to credit
  reporters in the release notes unless you prefer to stay anonymous.

As a small research team we cannot offer a paid bug bounty, but we genuinely
appreciate responsible disclosure.

## Scope

**In scope:** the FastAPI backend, the Vue frontend, the anonymization
pipeline, the redacted-PDF export, and the official Docker images.

**Out of scope:** vulnerabilities in third-party dependencies (report those
upstream; we track them via Dependabot and the security workflow), issues that
require a compromised host, the absence of authentication (deliberate — the app
is designed to run behind an institutional auth proxy), and misconfiguration
already called out in [`docs/SECURITY.md`](../docs/SECURITY.md).
