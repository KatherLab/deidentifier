# Annotation formats

The harness reads two formats. Point `--input` at a single file, a directory,
or a `.zip` archive — directories and archives are walked recursively, and
macOS junk (`__MACOSX`, `._*`) is skipped.

## JSONL (native)

One document per line:

```json
{"document_id": "doc-001", "text": "Patient: Max Mustermann, geb. 01.02.1980", "entities": [{"start": 9, "end": 23, "entity_type": "PERSON_NAME", "text": "Max Mustermann"}, {"start": 30, "end": 40, "entity_type": "DATE_OF_BIRTH"}]}
```

| Field | Required | Notes |
|---|---|---|
| `document_id` | yes | Any stable identifier. Appears in the report. |
| `text` | yes | The full document text, exactly as the pipeline will see it. |
| `entities[].start` / `.end` | yes | **Unicode code point offsets** into `text`; `end` exclusive. |
| `entities[].entity_type` | yes | A canonical type, or any label you map with `--label-map`. |
| `entities[].text` | no | Validated against the offsets when present. Include it — it catches offset drift immediately. |

Offsets are Python string indices. If you generate them from another tool,
verify that `text[start:end]` is the expected string before trusting a run.

## INCEpTION UIMA-CAS JSON

The export format used by the LLMAIx annotation workflow. The document text
lives in the `uima.cas.Sofa` feature structure (`sofaString`) and each
annotation is a `custom.Span` with `begin`, `end`, and `label`. Parsed with
plain `json` — no `cassis` dependency.

Typical use: export your INCEpTION project, then

```bash
uv run python -m backend.src.evaluation.run \
    --input annotations-export.zip --output results.json
```

## Label mapping

Annotation projects rarely use our twelve type names. Unknown labels map to
`OTHER_PII` with a warning; supply a mapping instead:

```json
{
  "patientname": "PERSON_NAME",
  "doctorname": "PERSON_NAME",
  "klinik": "ORGANIZATION",
  "fallnummer": "ID_NUMBER"
}
```

```bash
--label-map map.json
```

Lookup is case-insensitive. A default map already covers the common LLMAIx
labels (`patientname`, `firstname`, `lastname`, `name`, `patientid`,
`dateofbirth`, `age`, `patientgender`, `sex`) plus the identity mapping of our
own type names.

## Choosing what to annotate

Two decisions shape what the numbers mean:

**Which types.** If you only annotate names and IDs, every date the pipeline
redacts counts as a false positive and precision looks terrible. Use
`--restrict-to-gt-types` to score only the types your ground truth actually
covers.

**Boundaries.** Does `Herrn Wolfgang Schäfer` include `Herrn`? Does `Dr. med.
Anna Beispiel` include the title? Be consistent — that choice drives the gap
between exact-span and overlap metrics ([Metrics](metrics.md)). For the
question that matters, "was the identifier removed?", the character-level and
overlap metrics are the robust ones.

## Building a set

- **Cover your document types.** Discharge letters, radiology reports, lab
  results, referrals and scanned faxes fail in different ways.
- **Include hard cases on purpose.** OCR-damaged text, the same surname for
  patient and physician, identifiers inside tables, names in signature blocks.
- **A few dozen documents already tell you something**, especially about
  document-level leakage. Perfect coverage is not the entry price.
- **Store it like patient data**, because it is. Annotated documents are full
  text with the identifiers marked.
