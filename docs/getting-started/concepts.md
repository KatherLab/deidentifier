# Core concepts

Five ideas explain every behaviour in the app.

## 1. The source is immutable; detectors only propose spans

No generative model ever rewrites your document. Detectors — including the
LLM — propose **spans**: a start offset, an end offset, the exact text, and an
entity type. Deterministic code then applies replacements to the unchanged
source.

Two consequences you can rely on:

- Every span is verified against the source before use. If the text at those
  offsets does not match what the detector claimed, the span is rejected and
  logged as a warning.
- The review view highlights the **original** text. What you see marked is
  literally what will be replaced.

The LLM never returns offsets — it returns strings, which deterministic code
then locates in the source (exactly, then via umlaut variants, de-hyphenation,
and whitespace normalization). A mention the model reports but that cannot be
located becomes a warning, never a silent omission.

## 2. Recall over precision

A missed name is worse than an over-redacted word. The defaults over-redact,
and preservation is opt-in per entity in the review view. This is also why an
enabled-but-unconfigured detector **fails the request** instead of quietly
producing a thinner result: a document that was not fully checked must never
look like one that passed.

## 3. Entity types and the default policy

Twelve deliberately coarse types. Each has a default transformation:

| Entity type | Label (German UI) | Default | Result |
|---|---|---|---|
| `PERSON_NAME` | Person | `CONSISTENT_TAG` | `[PERSON_1]`, `[PERSON_2]`, … — the same person keeps the same number |
| `DATE_OF_BIRTH` | Geburtsdatum | `TYPE_MASK` | `[GEBURTSDATUM]` |
| `OTHER_DATE` | Datum | `PRESERVE` | unchanged — clinical timelines stay usable |
| `AGE` | Alter | `TYPE_MASK` | `[ALTER]` |
| `ADDRESS` | Adresse | `TYPE_MASK` | `[ADRESSE]` |
| `PHONE` | Telefon | `TYPE_MASK` | `[TELEFON]` |
| `EMAIL` | E-Mail | `TYPE_MASK` | `[E-MAIL]` |
| `URL` | URL | `TYPE_MASK` | `[URL]` |
| `ID_NUMBER` | ID-Nummer | `TYPE_MASK` | `[ID]` |
| `ORGANIZATION` | Organisation | `TYPE_MASK` | `[ORGANISATION]` — hospitals, practices, employers, and the units inside them (`Klinik für Kardiologie`, `Station 4B`) |
| `PROFESSION` | Beruf | `TYPE_MASK` | `[BERUF]` |
| `OTHER_PII` | Sonstige | `TYPE_MASK` | `[PII]` |

The five transformations: `TYPE_MASK` (placeholder), `CONSISTENT_TAG`
(numbered per distinct value), `GENERALIZE` (a date becomes its year),
`REMOVE` (`[GESCHWÄRZT]`), `PRESERVE` (unchanged).

The placeholders above are the German ones. They follow the run's **output
language**, chosen in
[advanced settings](../user-guide/advanced-settings.md#sprache-des-ergebnisses-output-language)
and fixed at submit — an English run writes `[DATE_OF_BIRTH]` and `[REDACTED]`.

!!! note "Preserved dates are a deliberate trade-off"

    `OTHER_DATE → PRESERVE` keeps admission, procedure, and discharge dates in
    the text because most downstream uses need them. Combined with other
    quasi-identifiers, dates can still narrow a person down. Change it in the
    [advanced settings](../user-guide/advanced-settings.md) when your use case
    does not need them.

## 4. Detectors

| Detector | What it is good at |
|---|---|
| `rules` | Structured identifiers where a model might drift on format: e-mail, URL, phone/fax, IBAN, postal codes, numeric dates, labelled IDs (`Pat.-Nr.`, `Fallnummer`, `Versichertennummer`, `geb.`, …), and hospital units (`Klinik für …`, `Abteilung für …`, `Station 4B`). Context-aware — a bare number is not an ID without a label, and a generic `die Station` in running text is not a unit. |
| `llm` | Everything unstructured, above all names in German clinical prose. This is the primary detector. |
| `mock` | Fixed fixture strings, for tests and offline development. Production refuses to start with it enabled. |

They run together and their results are merged: exact duplicates combine
(keeping both detectors as provenance), and where spans overlap the longer one
wins. Exactly one transformation ever applies to a character.

Long documents are split into **overlapping chunks** for the LLM, and detection
runs **multiple independent passes** whose results are unioned — a recall-first
safety net against run-to-run model variance.

## 5. Validation is a second opinion, never an edit

After the transformation, an independent pass re-scans the **output**:

1. no redacted text may remain anywhere,
2. the rule detectors run again on the output,
3. labelled fields (`Patient:`, `Name:`, `Anschrift:`) followed by
   non-redacted content are flagged,
4. optionally the LLM audits the output for remaining PII and for indirect
   identification risk.

Findings become warnings and set the status — `FAIL` for anything critical,
`REVIEW_REQUIRED` for a warning, `PASS` when only informational notes remain.
**Validation never edits the output.** See
[Warnings & validation](../user-guide/validation.md).

## Nothing is stored

There is no database. A document lives in memory for the duration of the
request, plus a short-lived in-process cache (15 minutes) that exists so your
review-view corrections do not have to repeat the expensive detection step.
When that cache entry expires the app simply re-sends the source text from your
browser. See [Data retention](../DATA_RETENTION.md).
