# User guide

The app has two screens: an input screen and a result screen. This section
covers both in detail.

| Page | Covers |
|---|---|
| [Anonymizing documents](anonymizing.md) | Input formats, batches, scanned PDFs, what the progress stages mean |
| [Reviewing the result](review.md) | The panels, entity highlights, per-entity corrections, manual redaction |
| [Advanced settings](advanced-settings.md) | Per-type policy, always-redact and always-keep terms, extra LLM instructions, forced OCR |
| [Warnings & validation](validation.md) | What `PASS` / `Prüfbedarf` / `fehlgeschlagen` mean and what to do about each |
| [Exporting](export.md) | Text, redacted PDF, ZIP, and the filename trade-off |

## Before you start

!!! warning "The result is not proof of legal anonymization"

    The tool supports a human review; it does not replace one. Read the
    anonymized output before it leaves your hands, and validate the pipeline
    on your own documents ([Evaluation](../evaluation/index.md)) before
    trusting it for a new document type.

Two habits worth forming:

- **Check the header chip.** It warns when document content will leave this
  machine, or when an enabled detector is not configured.
- **Take `Prüfbedarf` seriously.** It means the validator found something in
  the *output* that looks like it should not be there.

## Interface language

The interface speaks **German, English, French and Spanish**. It opens in the
language your browser asks for and falls back to German; the globe button in
the header switches it at any time, and that choice is remembered in this
browser (a UI preference — no document content is ever stored).

That covers everything the app *says* — including the notices and warnings the
backend produces. What a run *writes into the document* is a separate setting:
the placeholders (`[GEBURTSDATUM]` vs `[DATE_OF_BIRTH]`) follow the **output
language** of that run, which defaults to the interface language and is fixed
when you press Anonymisieren. See
[Advanced settings](advanced-settings.md#sprache-des-ergebnisses-output-language).

This documentation uses the German labels for anything you click, so the docs
and the default interface stay aligned.
