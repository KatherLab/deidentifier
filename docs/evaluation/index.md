# Evaluation

The only honest answer to "how well does this anonymize?" is a measurement on
your own documents. The repository ships a standalone harness for exactly that.
It is a CLI, not part of the web app — it never touches the API and stores
nothing.

```bash
uv run python -m backend.src.evaluation.run \
    --input annotations.jsonl \
    --output evaluation-results.json \
    --detectors rules,llm
```

## What you need

1. **Annotated documents** — text plus the character spans of the identifiers
   in it. Our JSONL format or INCEpTION UIMA-CAS exports (the LLMAIx annotation
   format), as single files, directories, or `.zip` archives. See
   [Annotation formats](data-formats.md).
2. **A configured pipeline** — the same `.env` your deployment uses, so you
   measure what you actually run. `--detectors` overrides `DETECTORS` for a
   single run, which is how you compare configurations.

## Options

| Option | Purpose |
|---|---|
| `--input` | JSONL file, CAS JSON file, directory, or `.zip`. |
| `--output` | Where the JSON report is written. |
| `--mode detection` (default) | Scores everything the detectors **find**. |
| `--mode redaction` | Scores what the default policy actually **masks** — preserved clinical dates count as leaks if they were annotated. |
| `--detectors` | Override `DETECTORS`, e.g. `rules` vs `rules,llm`. |
| `--label-map map.json` | Map your annotation labels onto the canonical entity types. |
| `--restrict-to-gt-types` | Score only predicted spans whose type the ground truth annotates — fair precision when your annotations cover a subset of PII types. |
| `--include-sensitive-text` | **Sensitive.** Include the literal text of missed entities in the report, for debugging. |

## Which mode to use

- **`detection`** answers "does the pipeline *see* the identifiers?" Use it to
  compare models and detector configurations.
- **`redaction`** answers "does the output still contain them?" Use it to
  decide whether a policy is acceptable for a given purpose. Under the default
  policy, `OTHER_DATE` is preserved, so an annotation set that marks dates will
  show them as leaks here — correctly.

Run both. A pipeline that detects everything but preserves it by policy is fine
for one use case and unacceptable for another.

## Reading the output

The console summary leads with the number that matters:

```text
==============================================================
Documents evaluated:        120
DOCUMENT-LEVEL LEAKAGE:     7 document(s) with leaked characters (5.8%)
  leaked characters total:  213
  missed entities total:    11
--------------------------------------------------------------
Char-level (micro):         P 0.9721  R 0.9934  F1 0.9826
Span overlap (micro):       P 0.9615  R 0.9902  F1 0.9757
Span exact (micro):         P 0.8830  R 0.9094  F1 0.8960
--------------------------------------------------------------
Per entity type (GT):       entities  detected  overlap recall
  PERSON_NAME                    412       410          0.9951
  …
==============================================================
```

(Illustrative numbers — run it on your own data.)

**Document-level leakage is the headline.** An F1 of 0.98 sounds excellent and
still means one document in twenty carries a name. For a release decision, the
percentage of documents with at least one leaked character is the number to
argue about. See [Metrics](metrics.md).

The JSON report contains the same aggregates plus per-document results, so you
can find the documents that leaked and look at them.

## Privacy of the report

By default the report contains **no literal entity text** — counts, offsets,
and types only, so it can be shared and archived.

`--include-sensitive-text` adds the literal text of missed entities. That is
genuinely useful for debugging a detector, and it turns the report into a file
containing real identifiers. Treat it like the source documents: never commit
it, never attach it to an issue.

## Annotated data is an asset

Every document you annotate improves your ability to compare configurations —
and the same annotations are training data for a future in-house detection
model. Store them with the same care as the documents they came from.
