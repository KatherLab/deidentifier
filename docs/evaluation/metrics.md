# Metrics

## Document-level leakage — the headline

```json
"leakage": {
  "documents_with_leaked_chars": 7,
  "documents_clean": 113,
  "leakage_rate": 0.0583,
  "total_leaked_chars": 213,
  "total_missed_entities": 11
}
```

A document "leaks" when at least one annotated identifier character was not
covered by the pipeline. This is deliberately the strictest, most pessimistic
view, and it is the one to lead with — corpus-level F1 averages away exactly
the failure that matters. A 0.98 F1 with a 6 % leakage rate means one document
in seventeen carries an identifier.

For a release decision, argue about `leakage_rate` and look at the documents
behind it.

## Character-level P/R/F1

Every character is classified as redacted or not, and precision/recall/F1 are
computed over the "redacted" class. Whitespace and punctuation
(` ,.!?:;-()"'` and newlines/tabs) are excluded from scoring, matching LLMAIx
semantics so numbers are comparable with the sibling project.

| | Meaning |
|---|---|
| **Recall** | Share of identifier characters that were redacted. **The privacy metric.** |
| **Precision** | Share of redacted characters that really were identifiers. The utility metric — low precision means an over-redacted, less useful document. |
| **F1** | Their harmonic mean. Convenient, and the easiest number to hide behind. |

Character-level metrics are robust to boundary disagreements: redacting
`Herrn Wolfgang Schäfer` where the annotation marks only `Wolfgang Schäfer`
costs a little precision, not a whole entity.

## Span-level metrics

Reported twice:

- **overlap** — a predicted span counts as a match if it overlaps an annotated
  one. This answers "did the pipeline notice this identifier?"
- **exact** — start and end must match exactly. This answers "did it get the
  boundaries right?"

Exact is always lower, often much lower, and that gap is usually an annotation
convention difference (titles, salutations, trailing punctuation) rather than a
detection failure. Read overlap for privacy questions and exact only when you
care about boundaries.

## Micro vs macro

- **micro** pools all documents, so long documents weigh more.
- **macro** averages per-document scores, so every document weighs the same.

Macro is the better summary when document length varies widely; micro is the
better one when you care about total volume. When they diverge, look at the
outliers.

## Per entity type

```text
Per entity type (GT):       entities  detected  overlap recall
  PERSON_NAME                    412       410          0.9951
  ID_NUMBER                       88        83          0.9432
  ADDRESS                         51        44          0.8627
```

Recall per annotated type, using overlap matching. This is where you see
*which* identifier class is failing, which is what you act on: a weak
`ID_NUMBER` recall points at the rule detector, a weak `PERSON_NAME` recall at
the model.

## Detection vs redaction mode

The same metrics computed against two different predictions:

| Mode | Predicted spans are… |
|---|---|
| `detection` | everything the detectors found |
| `redaction` | only what the policy actually masks |

Under the default policy `OTHER_DATE` is preserved, so a date-annotating ground
truth shows near-perfect recall in `detection` and visible leakage in
`redaction` — correctly, on both counts. The gap between the two runs is
exactly the privacy cost of your policy choices.

## What these numbers do not tell you

- **Indirect identification.** A rare diagnosis plus a profession plus a small
  town can identify someone with no direct identifier present. Nothing here
  measures that; the LLM re-check flags it qualitatively at runtime.
- **OCR failures.** If OCR mangled a name, it is not in the extracted text and
  neither the pipeline nor your annotation sees it. Evaluate the OCR path on
  scans separately.
- **Generalization.** Scores hold for documents like the ones you annotated.
  A new document type is an unmeasured document type.
