# Build a Local Prototype for Anonymizing German Medical Documents

## Objective

Build a secure, locally deployable web application for evaluating anonymization and pseudonymization of predominantly German medical documents.

The primary user flow must be:

1. User uploads a document or pastes text.
2. User selects an anonymization policy.
3. The system extracts the text.
4. The system detects sensitive spans.
5. The system applies deterministic transformations to those spans.
6. The user receives anonymized text and can inspect the redactions.

The prototype is an internal evaluation tool, not a certified anonymization or compliance product.

Do not send document contents, extracted text, identifiers, filenames, prompts, logs, or telemetry to external services. All processing must be local.

## Core design principle

Never ask a generative model to rewrite the entire medical document.

The source text must remain immutable. Models may only propose spans or structured policies. All actual modifications must be performed by deterministic code using character offsets.

Use this processing pipeline:

```text
Document
  → text extraction
  → text normalization with offset preservation
  → rule-based candidate detection
  → model-based span detection
  → optional custom-policy detection
  → span merging and conflict resolution
  → deterministic transformation
  → independent leakage validation
  → result and review interface
```

## Scope of the first prototype

Support:

* pasted plain text;
* `.txt`;
* `.docx`;
* digitally generated `.pdf`;
* German and mixed German/English text;
* selectable predefined policies;
* a natural-language custom instruction;
* highlighted review of detected entities;
* anonymized plain-text output;
* JSON audit output without storing the source document;
* download and clipboard copy;
* entirely local operation.

For the initial version, do not attempt to reconstruct or export a visually redacted PDF or DOCX. Extract document text and return anonymized plain text.

Scanned PDFs may be detected, but OCR can initially be marked as unsupported or experimental. Design the extraction interface so that OCR can be added later.

## Suggested technology stack

Use:

* Python 3.12;
* FastAPI backend;
* Pydantic v2 schemas;
* React with TypeScript for the frontend;
* Vite for frontend development;
* PyMuPDF for PDF extraction;
* `python-docx` for DOCX extraction;
* Hugging Face Transformers or the official runtime required by the selected local PII model;
* pytest for backend tests;
* Vitest and React Testing Library for frontend tests;
* Playwright for one end-to-end happy-path test;
* Docker Compose for local deployment.

Keep the model behind an adapter. The application must work with a mock detector and rule-based detector before model weights are installed.

## Repository structure

Create a monorepo with this approximate structure:

```text
medical-anonymizer/
├── README.md
├── SECURITY.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── routes_anonymize.py
│   │   │   ├── routes_health.py
│   │   │   └── routes_models.py
│   │   ├── extraction/
│   │   │   ├── base.py
│   │   │   ├── plain_text.py
│   │   │   ├── docx.py
│   │   │   └── pdf.py
│   │   ├── detection/
│   │   │   ├── base.py
│   │   │   ├── rules.py
│   │   │   ├── privacy_filter.py
│   │   │   ├── mock.py
│   │   │   └── ensemble.py
│   │   ├── policy/
│   │   │   ├── schemas.py
│   │   │   ├── presets.py
│   │   │   ├── compiler.py
│   │   │   └── validation.py
│   │   ├── transformation/
│   │   │   ├── operators.py
│   │   │   ├── resolver.py
│   │   │   └── apply.py
│   │   ├── validation/
│   │   │   ├── leakage.py
│   │   │   └── quality.py
│   │   ├── schemas/
│   │   │   ├── entities.py
│   │   │   └── api.py
│   │   └── security/
│   │       ├── logging.py
│   │       └── file_handling.py
│   └── tests/
│       ├── fixtures/
│       ├── unit/
│       ├── integration/
│       └── evaluation/
└── frontend/
    ├── package.json
    ├── src/
    │   ├── app/
    │   ├── components/
    │   ├── api/
    │   ├── types/
    │   └── tests/
    └── e2e/
```

## Canonical entity schema

All detectors must return entities using exactly one canonical structure.

```python
from enum import StrEnum
from pydantic import BaseModel, Field, model_validator


class EntityType(StrEnum):
    PATIENT_NAME = "PATIENT_NAME"
    RELATIVE_NAME = "RELATIVE_NAME"
    CLINICIAN_NAME = "CLINICIAN_NAME"
    OTHER_PERSON_NAME = "OTHER_PERSON_NAME"

    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    EVENT_DATE = "EVENT_DATE"
    OTHER_DATE = "OTHER_DATE"
    AGE = "AGE"

    STREET_ADDRESS = "STREET_ADDRESS"
    POSTAL_CODE = "POSTAL_CODE"
    CITY = "CITY"
    REGION = "REGION"
    COUNTRY = "COUNTRY"

    PHONE = "PHONE"
    EMAIL = "EMAIL"
    URL = "URL"

    PATIENT_ID = "PATIENT_ID"
    CASE_ID = "CASE_ID"
    ACCESSION_ID = "ACCESSION_ID"
    INSURANCE_ID = "INSURANCE_ID"
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
    OTHER_IDENTIFIER = "OTHER_IDENTIFIER"

    HOSPITAL_NAME = "HOSPITAL_NAME"
    PRACTICE_NAME = "PRACTICE_NAME"
    EMPLOYER = "EMPLOYER"
    SCHOOL = "SCHOOL"
    CARE_HOME = "CARE_HOME"
    OTHER_ORGANIZATION = "OTHER_ORGANIZATION"

    PROFESSION = "PROFESSION"
    SIGNATURE = "SIGNATURE"
    USER_DEFINED = "USER_DEFINED"


class EntitySpan(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    entity_type: EntityType
    confidence: float = Field(ge=0, le=1)
    detector: str
    detector_version: str
    rule_id: str | None = None
    metadata: dict[str, str | int | float | bool] = {}

    @model_validator(mode="after")
    def validate_span(self):
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if len(self.text) != self.end - self.start:
            raise ValueError("span text length does not match offsets")
        return self
```

Validate every detector result against the original text:

```python
assert source_text[entity.start:entity.end] == entity.text
```

Reject or quarantine any invalid span.

Use Unicode code-point indices consistently throughout the Python backend. The frontend must never independently recalculate offsets from modified text.

## Detection interface

Define a detector protocol:

```python
from typing import Protocol


class SpanDetector(Protocol):
    name: str
    version: str

    async def detect(
        self,
        text: str,
        enabled_types: set[EntityType] | None = None,
    ) -> list[EntitySpan]:
        ...
```

Implement the following detectors.

### 1. Rule-based detector

Create German-oriented recognizers for:

* email addresses;
* telephone and fax numbers;
* URLs;
* German and international IBANs;
* German postal codes;
* dates in common numeric and written formats;
* common patient-number labels;
* case numbers;
* insurance identifiers;
* accession numbers;
* document identifiers.

Examples of contextual labels to support:

```text
Pat.-Nr.
Patientennummer
Fallnummer
Fall-Nr.
Aufnahmenummer
Versichertennummer
KV-Nummer
Befundnummer
Proben-ID
Auftragsnummer
Aktenzeichen
Geburtsdatum
geb.
Telefon
Tel.
Mobil
Fax
E-Mail
```

Rules must have stable IDs such as:

```text
de.email.generic.v1
de.phone.contextual.v1
de.patient_id.labelled.v1
de.date.numeric.v1
de.iban.v1
```

Use context-aware rules where possible. For example, a generic number should not become a patient ID unless it appears near an appropriate label.

Do not automatically redact all numbers.

### 2. Local model adapter

Implement `PrivacyFilterDetector` as an adapter, not as tightly coupled application logic.

Configuration must include:

```env
PII_MODEL_PROVIDER=mock
PII_MODEL_PATH=
PII_MODEL_DEVICE=cpu
PII_MODEL_THRESHOLD=0.50
PII_MODEL_BATCH_SIZE=1
PII_MODEL_MAX_LENGTH=
```

Supported providers for the prototype:

```text
mock
privacy_filter
custom_huggingface
```

The adapter must:

* load weights only from a configured local path;
* fail closed if configured weights are missing;
* expose model name, version, threshold and device;
* return source-text offsets;
* map model labels to the canonical entity taxonomy;
* support configurable thresholds;
* avoid network downloads at application runtime;
* not use `trust_remote_code=True` unless explicitly documented and approved;
* expose a readiness status separately from application liveness.

When the model produces broad classes such as `PERSON`, preserve the broad result initially and refine it using surrounding context where safe. Do not fabricate a more specific class with high confidence.

For example, a person span following `Patient:` may be mapped to `PATIENT_NAME`; a span in a signature area may be mapped to `CLINICIAN_NAME`. Store the original model label in metadata.

### 3. Mock detector

Create a predictable mock detector for development and automated tests.

It should detect fixture values such as:

```text
Max Mustermann
Erika Musterfrau
Musterstraße 12
01307 Dresden
01.02.1980
PAT-123456
```

Never enable the mock detector in a production-mode configuration.

### 4. Ensemble detector

Run enabled detectors and merge their results.

Retain detector provenance. When more than one detector finds the same span, store all supporting detections in metadata and combine confidence conservatively.

## Overlap resolution

Implement deterministic overlap handling before any transformations.

Rules:

1. Exact duplicate spans are merged.
2. A labelled structured identifier should normally override a partial numeric match.
3. A longer address span may contain postal code and city child spans.
4. Nested entities may be retained internally but only one transformation may be applied to a character.
5. Explicit user-preserve rules override redaction rules.
6. Explicit user-defined redactions override default preservation.
7. Lower-confidence overlapping spans must never silently delete a higher-confidence span.
8. Every conflict must produce a traceable resolution record.

Use a `ResolvedSpan` structure that includes:

```python
class ResolutionDecision(BaseModel):
    selected_span: EntitySpan
    supporting_spans: list[EntitySpan]
    rejected_spans: list[EntitySpan]
    reason: str
```

Sort selected transformations by descending start offset before modifying the text.

## Policy model

Do not pass a raw custom prompt directly into the redaction model.

Convert user intent into a structured policy.

Define transformation operators:

```python
class TransformationType(StrEnum):
    REMOVE = "REMOVE"
    TYPE_MASK = "TYPE_MASK"
    CONSISTENT_TAG = "CONSISTENT_TAG"
    GENERALIZE = "GENERALIZE"
    PARTIAL_MASK = "PARTIAL_MASK"
    DATE_SHIFT = "DATE_SHIFT"
    SURROGATE = "SURROGATE"
    PRESERVE = "PRESERVE"
```

Define a policy schema:

```python
class EntityPolicy(BaseModel):
    entity_type: EntityType
    transformation: TransformationType
    minimum_confidence: float = Field(default=0.5, ge=0, le=1)
    options: dict[str, str | int | float | bool] = {}


class AdditionalConcept(BaseModel):
    name: str
    instruction: str
    transformation: TransformationType = TransformationType.TYPE_MASK


class AnonymizationPolicy(BaseModel):
    name: str
    version: str
    entity_policies: list[EntityPolicy]
    additional_concepts: list[AdditionalConcept] = []
    preserve_terms: list[str] = []
    redact_terms: list[str] = []
    date_shift_days: int | None = None
    strict_validation: bool = True
```

## Preset policies

Implement at least three policies.

### Research Safe

Aggressive policy intended for preparing evaluation data.

Default behavior:

* remove or type-mask all person names;
* remove all direct contact information;
* remove street addresses;
* remove patient, case, accession and insurance identifiers;
* remove signatures;
* generalize date of birth to birth year or age band;
* transform event dates using a consistent document-level date shift;
* redact employers, schools, care homes and rare professions;
* preserve diagnoses, medications, measurements and clinical findings;
* flag unusual indirect identifiers for review.

### Internal Clinical Sharing

Intended for internal examples where clinical context should remain useful.

Default behavior:

* redact patient and relative names;
* redact direct contact details;
* redact street addresses;
* redact patient-specific identifiers;
* generalize date of birth;
* preserve clinician names;
* preserve hospital and practice names;
* preserve clinical event dates unless explicitly changed;
* flag rare occupations and unusually specific locations.

### Custom

Start from `Internal Clinical Sharing` and apply a structured set of user changes.

The frontend must show the interpreted policy before processing or beside the result. The user should be able to see statements such as:

```text
Redact patient and relative names
Preserve clinician names
Preserve hospital names
Convert birth dates to year only
Keep treatment dates
Also redact employers and occupations
```

## Custom-instruction compiler

Create a `PolicyCompiler` interface:

```python
class PolicyCompiler(Protocol):
    async def compile(
        self,
        instruction: str,
        base_policy: AnonymizationPolicy,
    ) -> AnonymizationPolicy:
        ...
```

For the initial prototype, implement two compilers.

### Deterministic compiler

Support a limited set of explicit German and English phrases.

Examples:

```text
Ärztenamen behalten
Namen der Ärzte nicht entfernen
Krankenhausnamen behalten
Behandlungsdaten behalten
Geburtsdatum nur als Jahr
Berufe ebenfalls entfernen
Arbeitgeber anonymisieren
Postleitzahl teilweise schwärzen
Keep clinician names
Do not redact hospital names
Redact employers
Keep treatment dates
```

Parse these into structured policy modifications.

### Optional local LLM compiler

Create an adapter for a locally hosted instruction model.

The model may only return JSON matching `AnonymizationPolicyPatch`.

It must not receive document text. It receives only:

* the user instruction;
* the base policy;
* the available entity types;
* the available transformations.

Validate the returned JSON with Pydantic. Reject unsupported types, transformations, or contradictory rules.

Do not execute arbitrary strings or model-generated code.

When the policy compiler is uncertain, return a warning and leave the base policy unchanged for that instruction.

## Transformation behavior

Implement all transformations as pure deterministic functions.

### Type mask

Examples:

```text
Max Mustermann → [PATIENT_NAME]
Musterstraße 12 → [STREET_ADDRESS]
PAT-123456 → [PATIENT_ID]
```

### Consistent tags

Within a document, repeated mentions of the same normalized value must receive the same tag:

```text
Max Mustermann → [PERSON_1]
Herr Mustermann → [PERSON_1] only when matching is sufficiently reliable
Erika Musterfrau → [PERSON_2]
```

Do not merge people using surname alone unless the policy explicitly enables heuristic coreference.

### Remove

Replace the span with:

```text
[REDACTED]
```

Do not collapse surrounding paragraphs.

### Generalize dates

Support:

```text
01.02.1980 → 1980
01.02.1980 → [DOB_YEAR_1980]
01.02.1980 → [AGE_BAND_40_49]
```

Age must be calculated only when an appropriate reference date is known. Do not use the server’s current date implicitly for historic documents.

### Date shifting

Apply one deterministic shift to all shiftable dates in one document.

Requirements:

* preserve relative intervals;
* do not shift date of birth unless configured;
* handle leap days;
* store the shift only in process memory for the request;
* do not expose the shift in ordinary anonymized output;
* include it only in privileged evaluation metadata when explicitly enabled.

### Partial mask

Support configurable transformations such as:

```text
01307 → 01***
+49 351 1234567 → +49 *** *******
ABCD123456 → ****123456
```

### Preserve

A preserved span remains unchanged, but it may still be displayed in the review UI as intentionally preserved.

### Surrogates

Define the interface but mark surrogate replacement as experimental.

Surrogates must come from local deterministic generators. Do not use an external API.

Preserve plausible formatting and gendered titles only when the data required to do so is available. Otherwise use neutral replacements.

## API design

### `POST /api/v1/anonymize/text`

Request:

```json
{
  "text": "Patient: Max Mustermann, geboren am 01.02.1980 ...",
  "policy_id": "internal-clinical-sharing",
  "custom_instruction": "Geburtsdatum nur als Jahr. Ärztenamen behalten.",
  "options": {
    "include_entities": true,
    "include_audit": true,
    "run_validation": true
  }
}
```

Response:

```json
{
  "request_id": "uuid",
  "source_length": 1250,
  "anonymized_text": "Patient: [PATIENT_NAME], geboren 1980 ...",
  "policy": {
    "name": "Internal Clinical Sharing",
    "version": "1.0",
    "summary": [
      "Patient names are redacted",
      "Clinician names are preserved",
      "Dates of birth are generalized to year"
    ]
  },
  "entities": [
    {
      "start": 9,
      "end": 23,
      "text": "Max Mustermann",
      "entity_type": "PATIENT_NAME",
      "confidence": 0.98,
      "detector": "privacy_filter",
      "transformation": "TYPE_MASK",
      "replacement": "[PATIENT_NAME]",
      "status": "REDACTED"
    }
  ],
  "validation": {
    "status": "PASS",
    "warnings": []
  },
  "timing_ms": {
    "extraction": 0,
    "detection": 135,
    "policy": 2,
    "transformation": 1,
    "validation": 85,
    "total": 223
  }
}
```

### `POST /api/v1/anonymize/file`

Use multipart form data:

```text
file
policy_id
custom_instruction
include_entities
include_audit
run_validation
```

Apply conservative upload limits:

```text
Maximum file size: configurable, default 10 MB
Maximum extracted text: configurable, default 500,000 characters
Allowed extensions: txt, docx, pdf
```

Reject password-protected, malformed or unsupported files with a clear message.

### `POST /api/v1/policy/preview`

Compile a custom instruction without receiving document text.

Request:

```json
{
  "policy_id": "internal-clinical-sharing",
  "custom_instruction": "Berufe und Arbeitgeber entfernen, Krankenhausnamen behalten."
}
```

Return the resulting structured policy, human-readable summary and warnings.

### `GET /api/v1/policies`

Return available policies and their descriptions.

### `GET /api/v1/models`

Return only operational metadata:

```json
{
  "detectors": [
    {
      "name": "privacy_filter",
      "version": "configured-version",
      "ready": true,
      "device": "cpu"
    }
  ]
}
```

Never return local filesystem paths.

### `GET /health/live`

Return whether the web process is alive.

### `GET /health/ready`

Return whether configured detectors are loaded and ready.

## Document extraction

Create a common result type:

```python
class ExtractedDocument(BaseModel):
    text: str
    source_type: str
    pages: list["PageRange"] = []
    warnings: list[str] = []
    metadata_removed: bool = True


class PageRange(BaseModel):
    page_number: int
    start: int
    end: int
```

### TXT

* detect UTF-8;
* support UTF-8 with BOM;
* reject binary content;
* do not silently decode arbitrary bytes with data loss.

### DOCX

Extract:

* paragraphs;
* tables;
* headers;
* footers.

Separate logical blocks with newlines.

Add warnings if potentially unsupported content is detected, including:

* text boxes;
* comments;
* tracked changes;
* embedded objects.

Do not save an altered copy of the uploaded document.

### PDF

Use block-aware text extraction.

Preserve:

* reading order as reliably as possible;
* page boundaries;
* paragraph or block separation.

Detect likely scanned PDFs when pages have little or no extractable text. Return:

```text
This PDF appears to contain scanned images. OCR is not enabled in this prototype.
```

Do not claim that a scanned document was anonymized when no text was extracted.

## Leakage validation

After transformation, run a separate validation stage.

Implement these checks:

1. Original detected direct identifiers must not remain in output unless their policy is `PRESERVE`.
2. Rule-based recognizers run again on anonymized output at a more sensitive setting.
3. The model detector runs again at a configurable lower threshold.
4. Search for unmodified source substrings associated with redacted entities.
5. Detect likely signature blocks.
6. Detect suspicious labelled fields such as `Patient:`, `Name:`, `Geburtsdatum:` followed by non-redacted content.
7. Detect unresolved policy conflicts.
8. Confirm that replacements have not changed protected clinical spans outside selected offsets.

Validation output:

```python
class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"


class ValidationWarning(BaseModel):
    start: int | None = None
    end: int | None = None
    text: str | None = None
    category: str
    message: str
    severity: ValidationSeverity
    detector: str


class ValidationResult(BaseModel):
    status: Literal["PASS", "REVIEW_REQUIRED", "FAIL"]
    warnings: list[ValidationWarning]
```

Behavior:

* `PASS`: no unresolved warnings;
* `REVIEW_REQUIRED`: informational or medium-confidence warnings remain;
* `FAIL`: a high-confidence direct identifier appears to remain.

Do not silently perform new transformations during validation. Show warnings to the user.

## Frontend

Build a single-page application optimized for simplicity.

### Main screen

Include:

* title: `Medical Document Anonymizer`;
* local-processing notice;
* paste-text area;
* drag-and-drop upload area;
* policy selector;
* collapsible advanced section;
* custom instruction field;
* anonymize button.

Use clear wording such as:

```text
Documents are processed locally by this installation. Do not use the result as proof that a document is legally anonymous.
```

### Result screen

Display:

1. anonymized text;
2. copy button;
3. download `.txt` button;
4. status badge: Passed, Review required or Failed;
5. entity count by type;
6. toggle between:

   * anonymized result;
   * source review;
   * policy summary;
   * warnings.

The review view should highlight entities over the immutable source text.

Suggested visual distinctions:

* red: removed;
* orange: generalized;
* blue: pseudonymized or consistently tagged;
* gray outline: preserved intentionally;
* yellow: validation warning.

Do not rely on color alone. Include text labels and accessible patterns.

### Entity review

Selecting a highlighted entity must show:

```text
Detected text
Entity type
Confidence
Detector
Transformation
Replacement
Reason for overlap resolution, when relevant
```

For the prototype, allow the user to change an individual entity action before regenerating the result:

* redact;
* preserve;
* change entity type;
* choose transformation.

Represent such changes as explicit policy overrides, then rerun deterministic transformation. Do not mutate the current output directly.

### Error handling

Present user-friendly messages for:

* unsupported file;
* file too large;
* scanned PDF;
* extraction failure;
* model unavailable;
* invalid custom instruction;
* output requiring review.

Never show stack traces to users.

## Security and privacy requirements

The application handles highly sensitive data.

Implement the following:

* no analytics;
* no third-party fonts, scripts or CDNs;
* no external model calls;
* no remote model downloads at runtime;
* no document-content logging;
* no prompt logging;
* no raw request-body logging;
* no persistence by default;
* no browser local-storage persistence of document contents;
* no caching of responses containing text;
* restrictive CORS configuration;
* upload size limits;
* MIME and extension validation;
* random temporary filenames;
* cleanup of temporary files in `finally` blocks;
* restrictive temporary-file permissions;
* secure response headers;
* disabled Swagger UI in production mode or protected internal access;
* application logs containing only request ID, timing, content length, status and error category;
* configuration for deployment behind the hospital’s authentication proxy.

Set response headers for sensitive routes:

```text
Cache-Control: no-store
Pragma: no-cache
X-Content-Type-Options: nosniff
Content-Security-Policy: default-src 'self'
Referrer-Policy: no-referrer
```

Never include detected PII in error reporting.

Implement a structured safe logger. The logger should reject fields called:

```text
text
document
content
prompt
filename
entity_text
anonymized_text
```

unless an explicit insecure development flag is enabled. That flag must default to false and print a prominent startup warning.

## Data retention

Default behavior:

* process data only in memory;
* delete temporary uploaded files immediately after extraction;
* do not create a database;
* do not retain source documents;
* do not retain anonymized results;
* do not retain custom instructions.

For evaluation, create an optional export function that downloads a JSON file directly to the user. Do not store it server-side.

## Audit export

The downloadable audit JSON may include:

* application version;
* model versions;
* policy version;
* rule versions;
* source length;
* hash of source text using a deployment-specific keyed HMAC;
* detected entities;
* transformations;
* validation warnings;
* processing timings.

By default, exclude the literal entity text from the audit export.

Support an explicit privileged evaluation option to include entity text, clearly labelled as containing sensitive information.

## Testing

### Unit tests

Test:

* every regex recognizer;
* German date formats;
* offset correctness with German umlauts and Unicode;
* newline normalization;
* duplicate span merging;
* nested span resolution;
* transformations applied right to left;
* repeated-entity consistent tags;
* preserve overrides;
* custom redact overrides;
* date generalization;
* date shifting;
* partial masks;
* policy compiler validation;
* source text remains unchanged;
* no modification outside selected offsets;
* safe logger rejection.

Include examples containing:

```text
ä ö ü Ä Ö Ü ß
combining Unicode characters
hyphenated names
double surnames
titles such as Dr., Prof. Dr. and PD Dr.
German quotation marks
non-breaking spaces
```

### Integration tests

Test:

* text anonymization endpoint;
* TXT upload;
* DOCX with paragraphs and tables;
* PDF with multiple pages;
* unsupported file rejection;
* oversized upload rejection;
* missing model behavior;
* validation failure behavior;
* policy preview;
* no-cache response headers.

### End-to-end test

Create one Playwright test:

1. open the app;
2. paste a synthetic German discharge-letter example;
3. choose Research Safe;
4. enter `Ärztenamen behalten`;
5. run anonymization;
6. verify patient name is redacted;
7. verify clinician name remains;
8. verify birth date is generalized;
9. verify copy and download controls exist;
10. verify policy interpretation is visible.

### Evaluation test harness

Create a command:

```bash
python -m app.evaluation.run \
  --input path/to/annotated.jsonl \
  --policy research-safe \
  --output evaluation-results.json
```

Use a JSONL format:

```json
{
  "document_id": "synthetic-001",
  "text": "Patient Max Mustermann ...",
  "entities": [
    {
      "start": 8,
      "end": 22,
      "entity_type": "PATIENT_NAME"
    }
  ]
}
```

Calculate:

* exact span precision, recall and F1;
* overlap span precision, recall and F1;
* character-level precision, recall and F1;
* per-entity-type metrics;
* number and percentage of documents with at least one missed entity;
* number and percentage of documents with zero missed entities;
* false-positive characters;
* clinical-information removal rate, when protected annotations are supplied;
* processing time per document;
* model and rule version.

Do not treat overall F1 as the only result. Make document-level leakage prominent in the report.

## Synthetic fixture data

Use only clearly synthetic test documents in the repository.

Create at least 20 synthetic German examples covering:

* discharge letter;
* pathology report;
* radiology report;
* outpatient letter;
* operative report;
* laboratory text;
* referral;
* emergency-department note;
* text with a relative’s name;
* rare profession;
* employer;
* care-home name;
* signature;
* malformed formatting;
* OCR-like spacing errors;
* mixed German and English text;
* multiple patients mentioned;
* same surname for patient and physician;
* treatment date versus date of birth;
* exact identifiers embedded in tables.

Add a header to every fixture:

```text
SYNTHETIC TEST DATA – NO REAL PATIENT INFORMATION
```

## Configuration

Create `.env.example`:

```env
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
APP_MAX_UPLOAD_MB=10
APP_MAX_TEXT_CHARS=500000
APP_ENABLE_DOCS=true
APP_ALLOW_INSECURE_CONTENT_LOGGING=false

PII_MODEL_PROVIDER=mock
PII_MODEL_PATH=
PII_MODEL_DEVICE=cpu
PII_MODEL_THRESHOLD=0.50
PII_VALIDATION_THRESHOLD=0.30

ENABLE_LOCAL_POLICY_LLM=false
POLICY_LLM_PATH=
POLICY_LLM_DEVICE=cpu

ENABLE_OCR=false
TEMP_DIR=
```

Production mode must refuse to start when:

* mock detection is enabled;
* insecure content logging is enabled;
* an external model URL is configured;
* required local model files are missing.

Allow a separate `evaluation` environment where mock detection is permitted but is visibly labelled.

## Docker deployment

Create Dockerfiles for frontend and backend plus Docker Compose.

Requirements:

* runtime containers run as non-root;
* model weights are mounted read-only;
* no internet access is required after images and model artifacts are prepared;
* source and result data are not mounted as persistent volumes;
* temporary storage uses an ephemeral volume;
* frontend serves static files locally;
* backend exposes only the internal application port;
* include health checks.

Example services:

```text
frontend
backend
```

Do not add a database, Redis, message queue or object store for the prototype.

## Documentation

The README must include:

* project purpose;
* explicit prototype limitations;
* architecture diagram;
* local setup;
* Docker setup;
* model installation instructions;
* how to run with the mock detector;
* how to configure a local detector;
* API examples;
* policy examples;
* evaluation instructions;
* security assumptions;
* data-retention behavior;
* known unsupported document features.

Create `SECURITY.md` covering:

* sensitive-data handling;
* no-content logging;
* model-supply-chain considerations;
* temporary-file handling;
* dependency scanning;
* reporting security problems;
* deployment behind hospital authentication;
* recommendation for network isolation;
* warning that anonymization quality must be locally validated.

## Model integration boundary

Do not guess undocumented APIs for OpenAI Privacy Filter.

First implement the `SpanDetector` abstraction, mock detector, rules detector and all downstream behavior.

Then integrate Privacy Filter using its official model documentation and actual locally installed package or repository. Put any model-specific tokenization, label mapping and decoding entirely inside:

```text
backend/app/detection/privacy_filter.py
```

Add model-contract tests that verify:

* input text is returned unchanged by the detector;
* all offsets match the source;
* all confidence values are within 0–1;
* unsupported labels map to `USER_DEFINED` or produce a documented warning;
* long input is handled without silently truncating content;
* overlapping chunk predictions are merged consistently.

If the model cannot process the entire document in one call, use overlapping windows. Reconcile spans using original-document offsets. Never lose or duplicate characters at chunk boundaries.

## Performance targets for the prototype

On representative hardware, target:

* text request accepted within 100 ms excluding model inference;
* no quadratic processing for ordinary span merging;
* support at least 500,000 extracted characters with a clear resource limit;
* visible progress state for processing longer files;
* cancellation when the browser disconnects where feasible;
* deterministic transformations under the same policy and detections.

Do not optimize prematurely, but add timing instrumentation for each processing stage.

## Acceptance criteria

The prototype is complete when all of the following work:

1. A user can paste German medical text and receive anonymized text.
2. A user can upload TXT, DOCX and text-based PDF files.
3. The source text is never rewritten by a generative model.
4. Every redaction corresponds to a validated character span.
5. Rule and model detectors can run together.
6. The model implementation is replaceable through one adapter.
7. The user can select Research Safe, Internal Clinical Sharing or Custom.
8. A German custom instruction can change the structured policy.
9. The interpreted custom policy is visible to the user.
10. The user can preserve or redact an individual detected span.
11. The result identifies validation warnings.
12. No document content appears in normal logs.
13. Temporary files are removed after every request.
14. Automated tests cover offsets, transformations and primary APIs.
15. The app runs locally through Docker Compose.
16. The repository contains only synthetic example documents.
17. The evaluation command reports both aggregate metrics and document-level leakage.
18. The README clearly states that this prototype does not establish legal anonymization.

## Implementation order

Build the prototype in these milestones.

### Milestone 1: Safe text-only vertical slice

Implement:

* FastAPI;
* React UI;
* pasted-text input;
* mock detector;
* rule detector;
* canonical spans;
* Research Safe policy;
* type-mask transformation;
* result display;
* no-content logging;
* unit tests.

### Milestone 2: Documents and review

Implement:

* TXT, DOCX and PDF extraction;
* source highlighting;
* entity detail panel;
* downloadable output;
* overlap resolution;
* policy presets;
* validation warnings.

### Milestone 3: Real local model

Implement:

* Privacy Filter adapter;
* model configuration;
* model health status;
* threshold controls in developer configuration;
* long-document processing;
* model-contract tests;
* detector ensemble.

### Milestone 4: Custom policy

Implement:

* deterministic German instruction compiler;
* policy-preview endpoint;
* advanced frontend field;
* policy summary;
* per-span overrides;
* optional local LLM compiler adapter.

### Milestone 5: Evaluation and hardening

Implement:

* annotated JSONL evaluation;
* document-level leakage metrics;
* synthetic evaluation suite;
* Docker hardening;
* dependency scanning;
* security documentation;
* production-startup safety checks.

## Coding standards

Use:

* full type annotations;
* strict TypeScript;
* small modules with explicit interfaces;
* Pydantic validation at all API boundaries;
* pure functions for transformations;
* dependency injection for detectors;
* stable rule IDs and policy versions;
* meaningful tests rather than snapshot-only tests;
* comments explaining privacy-sensitive decisions.

Avoid:

* global mutable document state;
* hidden persistence;
* arbitrary prompt execution;
* raw model output reaching the frontend without validation;
* redaction by global string replacement;
* reconstructing offsets after modifying text;
* logging document samples for debugging;
* assumptions that names are ASCII;
* relying exclusively on regexes;
* relying exclusively on a generative LLM.

## Initial implementation deliverable

Start by producing:

1. the proposed file tree;
2. the canonical Pydantic schemas;
3. the detector interfaces;
4. the rule-based detector;
5. the span resolver;
6. deterministic transformation functions;
7. the text anonymization endpoint;
8. a minimal React interface;
9. backend unit tests;
10. a README with local startup instructions.

After the vertical slice works with synthetic German examples, integrate the real local PII model through the adapter. Do not block the rest of the prototype on model installation.
