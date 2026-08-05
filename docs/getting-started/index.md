# Getting started

Three pages, in order:

1. **[Installation](installation.md)** — Docker Compose for a real deployment,
   or a local dev setup with `uv` and `npm`.
2. **[Quickstart walkthrough](quickstart.md)** — your first document, from
   paste to reviewed result.
3. **[Core concepts](concepts.md)** — spans, detectors, policy, validation:
   the five ideas everything else builds on.

## What you need to decide first

The app runs out of the box with **no external services at all** — rule-based
detection on pasted text and native PDFs. That is enough to see how it works,
but it is not enough for real use: the rule detector alone will miss names.

Two decisions turn it into something usable:

| Decision | Where | Why it matters |
|---|---|---|
| **Which LLM endpoint detects PII?** | `OPENAI_API_BASE`, `LLM_MODEL` | The prompted LLM is the primary detector for German clinical text. Without it, only structured identifiers (dates, phone numbers, labelled IDs) are found. |
| **What happens to scanned PDFs?** | `OCR_ENGINE` | With `none` (the default) scanned PDFs are rejected with a clear message rather than silently returning an empty result. |

Both point at **base URLs you control**. See
[LLM endpoints](../operations/llm-endpoints.md) and
[OCR engines](../operations/ocr-engines.md).

!!! danger "Document content flows to whatever you configure"

    Every detection request sends document text to `OPENAI_API_BASE`, and
    every OCR request sends page images to the OCR endpoint. Point them at
    services inside your own network. The app shows a banner in the header
    when a configured endpoint is not local — treat that banner as a blocker,
    not a hint.
