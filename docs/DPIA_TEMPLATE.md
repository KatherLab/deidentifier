# DPIA template

A starting point for a Data Protection Impact Assessment (GDPR Art. 35) for a
deployment of this tool. **It is not legal advice and not a completed DPIA** —
your data protection officer owns the real document. Everything in *italics* is
a placeholder you must fill in.

---

## 1. Description of the processing

**Purpose.** *e.g. Removing direct identifiers from clinical documents so they
can be used for internal research / quality assurance / teaching.*

**Nature.** Documents are submitted through a web interface. Text is extracted
(with OCR for scans), rule-based recognizers and a prompted large language
model propose identifier spans, deterministic code applies replacements, an
independent validation pass re-scans the output, and the user reviews and
corrects the result before exporting it.

**Scope.** *Which document types, which departments, which volume per month.*

**Context.** An internal tool operated by *[institution]* on *[infrastructure]*,
reachable only from *[network]*, behind *[auth proxy]*.

**Data categories.** Special-category health data (GDPR Art. 9) plus the direct
identifiers within it: names, addresses, dates of birth, contact details, case
and insurance numbers.

**Data subjects.** Patients, their relatives, and clinical staff named in the
documents.

**Retention.** No server-side persistence. Documents live in request memory
plus a bounded in-process cache (15 minutes, extendable by the reviewer up to
a configurable ceiling of 12 hours). See
[Data retention](DATA_RETENTION.md).

## 2. Necessity and proportionality

**Lawful basis.** *e.g. Art. 6(1)(e) + Art. 9(2)(j) with [national provision],
or consent, or a research authorization.*

**Why processing is necessary.** Anonymization *is* a processing operation on
identifiable data; performing it is what reduces the risk downstream.

**Data minimization.** Only the submitted document is processed. No accounts,
no history, no analytics. The system stores nothing.

**Anonymization vs pseudonymization.** *State explicitly which one you are
claiming.* The tool's output is **not certified as anonymous data**; treat it
as pseudonymized unless your own evaluation and review process supports a
stronger claim.

## 3. Consultation

- Data protection officer: *[name, date]*
- Information security: *[name, date]*
- Clinical stakeholders: *[names]*
- Data subjects / patient representation: *[if applicable]*

## 4. Risks to data subjects

Start from the [Risk register](RISK_REGISTER.md) and record your own ratings:

| Risk | Likelihood | Severity | Overall |
|---|---|---|---|
| An identifier is missed and the output is treated as anonymous (P1) | | | |
| Document content is transferred outside the institution (P2) | | | |
| Re-identification through preserved quasi-identifiers (P3) | | | |
| Poor OCR hides identifiers (P4) | | | |
| Unauthorized access to the tool (S1) | | | |

## 5. Measures

| Measure | Status |
|---|---|
| Deployed behind an authenticating reverse proxy, TLS terminated there | |
| All model and OCR endpoints inside the institutional network — no external-endpoint banner in the UI | |
| Data processing agreements in place for any endpoint not operated by us | |
| `APP_ENV=production`; content logging disabled | |
| Pipeline evaluated on our own annotated documents; leakage rate recorded | |
| Documented human review step before any output is used | |
| Users trained that the output is not certified anonymous data | |
| Access limited to *[role/group]* | |
| Incident procedure covers "an identifier was found in an exported document" | |
| Review scheduled *[frequency]* | |

## 6. The questions people forget

**Where does document content actually go?** List every configured endpoint,
who operates it, whether it logs request bodies, and its retention.
[Data flow](DATA_FLOW.md) has the hop-by-hop picture.

**Is a hosted model API a transfer?** Yes — to a processor, and possibly to a
third country. Answer it explicitly rather than by omission.

**What happens to the exports?** The tool's retention story ends at the
download. Where do users put the files, and under what policy?

**How do you know it works?** "We use an LLM" is not an answer.
[Evaluation](evaluation/index.md) produces a document-level leakage rate on
your own documents — cite the number and the date.

**Who reviews the output, against what standard?** Name the role and the
criterion. The tool assumes this step exists.

## 7. Outcome

**Residual risk:** *low / medium / high*

**Approved by:** *[name, role, date]*

**Conditions:** *e.g. re-evaluate before adding a new document type; re-run the
evaluation after any model change.*

**Next review:** *[date]*
