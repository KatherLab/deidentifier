# Reviewing the result

The result screen is where the tool earns its keep: it shows you exactly what
was redacted, why, and lets you correct it.

<figure markdown>
  ![The result view](../assets/screenshots/result-overview.png)
</figure>

## The header

- **Status** — the leakage validator's verdict
  ([Warnings & validation](validation.md)).
- **Exportieren** — always acts on the anonymized result, whichever panels are
  visible ([Exporting](export.md)).
- **Neues Dokument** — discards everything and returns to the input screen.

## The panels

Chips above the panels toggle up to three views side by side:

| Chip | Panel |
|---|---|
| **Original** | The untouched upload (PDF sources render the original file) or the extracted source text. |
| **Prüfung** | *Quellprüfung* — the source text with entities highlighted. The main working view. |
| **Ergebnis** | The anonymized text, or the redacted PDF for PDF sources. |

In [expert mode](advanced-settings.md#expert-mode) the redacted PDF and the
anonymized text become separate chips, so you can show both at once.

## Reading the highlights

<figure markdown>
  ![The Quellprüfung panel with highlighted entities](../assets/screenshots/result-review-panel.png)
</figure>

Each mark is coloured by what happened to it, and the legend above the text
names the statuses actually present in this document — colour is never the only
signal:

| Status | Meaning |
|---|---|
| **Entfernt** | Replaced by a placeholder such as `[ADRESSE]`. |
| **Getaggt** | Replaced by a consistent tag such as `[PERSON_1]` — the same person carries the same number throughout. |
| **Verallgemeinert** | Reduced, e.g. a date to its year. |
| **Beibehalten** | Left visible, either by policy (clinical dates) or by your decision. |

A small purple dot marks an entity you changed. A yellow highlight is not an
entity at all — it is a passage a **validation warning** points at.

The counts under the panels (`Person 3 · Adresse 2 · …`) are clickable: each
click jumps to the next occurrence of that type.

## Correcting an entity

Click a mark to open the detail bar:

<figure markdown>
  ![The detail bar for a selected entity](../assets/screenshots/result-entity-selected.png)
</figure>

| Action | Effect |
|---|---|
| **Beibehalten** | Keep this passage visible. |
| **Schwärzen** | Redact a passage that was preserved. |
| Type dropdown | Correct a wrong type — the new type's transformation applies immediately. |
| **Zurücksetzen** | Undo your change for this entity. |

Every change re-runs the transformation **on the server** from the cached
detection: the anonymized text and the redacted-PDF preview refresh together,
and the original document is never modified. Corrections are per occurrence,
not per string.

!!! note "The LLM re-check does not repeat"

    The final LLM audit runs on the full run only. After a correction you get
    an informational note saying so. Press **Neues Dokument** and re-run if
    you want a fresh audit of the corrected output.

## Redacting something no detector found

Select any text in the *Quellprüfung* panel and a **Schwärzen** pill appears at
the end of the selection. The selected span becomes a first-class entity
(marked as *Manuelle Schwärzung*), goes through the same overlap resolution as
everything else, and applies to the export.

This is the right tool for the things detectors are weakest at: an unusual
identifier, a distinctive free-text detail, a nickname.

For a term that occurs many times — or that you want redacted in *every*
document of a batch — use *Immer schwärzen* in the
[advanced settings](advanced-settings.md) instead.

## Blacking out areas of a PDF

Signatures, letterheads, stamps, and photos are pixels, not text, so no text
detector can find them. The **Geschwärztes PDF** panel has two views: switch it
from **Vorschau** to **Bereiche schwärzen** and drag a rectangle over anything
that should be covered:

<figure markdown>
  ![The area redaction editor](../assets/screenshots/result-pdf-area-editor.png)
</figure>

The editor shows the **original** pages, not the redacted preview — the text
redaction is applied to the export on top of the areas you draw here.

- Click an existing rectangle to remove it.
- **Fertig** (or the **Vorschau** view) takes you back to the redacted preview;
  every change applies immediately, so nothing is lost either way.
- **Alle Bilder schwärzen** covers every embedded image the backend found, in
  one click.
- Areas apply to the redacted-PDF preview and export only; text exports are
  unaffected.
