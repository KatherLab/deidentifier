/**
 * TypeScript mirrors of the backend Pydantic schemas for the anonymize +
 * status endpoints (llmaixweb convention: hand-written domain types in
 * `frontend/types/`, imported by services, stores and components).
 *
 * NOTE on offsets: `start` / `end` are Unicode CODE POINT offsets into
 * `source_text` (Python string indices). JavaScript string indices are UTF-16
 * code units — convert via `Array.from(sourceText)` before slicing (see
 * `utils/textSegments.ts`).
 */

export type SourceType = 'paste' | 'txt' | 'pdf' | 'pdf-ocr' | 'docx'

export type EntityType =
  | 'PERSON_NAME'
  | 'DATE_OF_BIRTH'
  | 'OTHER_DATE'
  | 'AGE'
  | 'ADDRESS'
  | 'PHONE'
  | 'EMAIL'
  | 'URL'
  | 'ID_NUMBER'
  | 'ORGANIZATION'
  | 'PROFESSION'
  | 'OTHER_PII'

export type TransformationType =
  'TYPE_MASK' | 'CONSISTENT_TAG' | 'GENERALIZE' | 'REMOVE' | 'PRESERVE'

export type EntityStatus = 'REDACTED' | 'GENERALIZED' | 'TAGGED' | 'PRESERVED'

export type ValidationStatus = 'PASS' | 'REVIEW_REQUIRED' | 'FAIL'

export type WarningSeverity = 'INFO' | 'WARNING' | 'HIGH'

export interface EntityMetadata {
  /** True when this entity's transformation/type was overridden by the user. */
  overridden?: boolean
  /** True for user-defined spans created via manual selection (detector `user_manual`). */
  user_manual?: boolean
  [key: string]: unknown
}

export interface AnonymizedEntity {
  /** Unicode code point offset into `source_text` (inclusive). */
  start: number
  /** Unicode code point offset into `source_text` (exclusive). */
  end: number
  text: string
  entity_type: EntityType
  confidence: number
  detector: string
  transformation: TransformationType
  replacement: string | null
  status: EntityStatus
  metadata?: EntityMetadata | null
}

/**
 * Per-entity override for a re-run. `start`/`end`/`text` must exactly match a
 * detected entity from a previous response. Omitting `transformation` lets the
 * (possibly new) entity type's default policy apply.
 */
export interface Override {
  start: number
  end: number
  text: string
  transformation?: TransformationType
  entity_type?: EntityType
}

/**
 * A user-drawn blackout region on a PDF page (area-redaction editor).
 * Coordinates are normalized to 0–1000 of the page width/height with a
 * TOP-LEFT origin. Applied at PDF export only — text outputs are unaffected.
 */
export interface RedactArea {
  /** 1-based page number. */
  page: number
  x0: number
  y0: number
  x1: number
  y1: number
}

/** Bounding box of an embedded image on a page (normalized, top-left origin). */
export interface PageImageBox {
  x0: number
  y0: number
  x1: number
  y1: number
}

/** One rendered PDF page for the area-redaction editor. */
export interface PdfPageRender {
  page: number
  /** Page size in PDF points (aspect ratio; coordinates stay normalized). */
  width: number
  height: number
  /** PNG data URL of the rendered page. */
  image: string
  /** Embedded-image bounds — offered as one-click redaction suggestions. */
  image_boxes: PageImageBox[]
}

export interface PdfPagesResponse {
  pages: PdfPageRender[]
  /** True when the document has more pages than the backend render cap. */
  truncated: boolean
}

/**
 * Request-level policy: entity type → transformation, overlaying the backend
 * defaults. Only DEVIATIONS from the defaults need to be sent; omitted types
 * keep their default transformation.
 */
export type PolicyMap = Partial<Record<EntityType, TransformationType>>

/**
 * User-defined custom rules from the advanced settings (memory only). All
 * fields are optional on the wire — only non-empty values are sent.
 */
export interface CustomRules {
  /** Free-text addition to the LLM detection prompt (detection-time). */
  customInstruction: string
  /** Terms that are ALWAYS redacted, everywhere (detection-time). */
  redactTerms: string[]
  /** Detected spans with exactly this text stay visible (transformation-time). */
  preserveTerms: string[]
}

/** Fresh run from raw text (optionally with overrides, e.g. after a 410). */
export interface AnonymizeTextRequest {
  text: string
  overrides?: Override[]
  policy?: PolicyMap
  custom_instruction?: string
  redact_terms?: string[]
  preserve_terms?: string[]
}

/**
 * Cheap re-run from the backend's cached detection of a previous request.
 * Only `preserve_terms` is accepted here — `redact_terms` and
 * `custom_instruction` affect DETECTION and are baked into the cached result.
 */
export interface AnonymizeRerunRequest {
  request_id: string
  overrides: Override[]
  policy?: PolicyMap
  preserve_terms?: string[]
}

export type AnonymizeRequest = AnonymizeTextRequest | AnonymizeRerunRequest

/** Pipeline stage reported by the NDJSON anonymize stream. */
export type ProgressStage = 'ocr' | 'detection' | 'recheck'

/**
 * One `progress` line of POST /anonymize/stream. `done`/`total` are stage
 * units (OCR: pages; detection: chunk passes; recheck: chunks).
 */
export interface StreamProgressEvent {
  stage: ProgressStage
  done: number
  total: number
}

export interface ValidationWarning {
  category: string
  message: string
  severity: WarningSeverity
  /** Unicode code point offset into `source_text`, when located. */
  start: number | null
  end: number | null
}

export interface ValidationResult {
  status: ValidationStatus
  warnings: ValidationWarning[]
}

export interface TimingMs {
  extraction: number
  detection: number
  transformation: number
  validation: number
  total: number
}

export interface AnonymizeResponse {
  request_id: string
  source_type: SourceType
  source_text: string
  anonymized_text: string
  entities: AnonymizedEntity[]
  validation: ValidationResult
  warnings: string[]
  timing_ms: TimingMs
}

export interface DetectorStatus {
  name: string
  enabled: boolean
  ready: boolean
}

export interface ExternalEndpoint {
  name: string
  host: string
  local: boolean
}

export interface StatusLimits {
  max_upload_mb: number
  max_text_chars: number
}

export interface StatusResponse {
  app_env: string
  version: string
  detectors: DetectorStatus[]
  ocr_engine: string
  external_endpoints: ExternalEndpoint[]
  limits: StatusLimits
}
