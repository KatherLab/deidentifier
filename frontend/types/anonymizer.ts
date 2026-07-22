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

/** Fresh run from raw text (optionally with overrides, e.g. after a 410). */
export interface AnonymizeTextRequest {
  text: string
  overrides?: Override[]
}

/** Cheap re-run from the backend's cached detection of a previous request. */
export interface AnonymizeRerunRequest {
  request_id: string
  overrides: Override[]
}

export type AnonymizeRequest = AnonymizeTextRequest | AnonymizeRerunRequest

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
