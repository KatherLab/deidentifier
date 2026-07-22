/**
 * German display names + visual treatment for entity types, entity statuses,
 * transformations, validation statuses and warning severities.
 *
 * Accessibility rule: highlight colors are ALWAYS paired with a visible text
 * label (chip) — never color alone.
 */
import type {
  EntityStatus,
  EntityType,
  SourceType,
  TransformationType,
  ValidationStatus,
  WarningSeverity,
} from '@/types/anonymizer'

/** Source type → German display name (badge in the result header). */
export const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  paste: 'Eingabe',
  txt: 'Text',
  pdf: 'PDF',
  'pdf-ocr': 'PDF (OCR)',
  docx: 'DOCX',
}

export function sourceTypeLabel(type: string): string {
  return SOURCE_TYPE_LABELS[type as SourceType] ?? type
}

/** Entity type → German display name (chips, legend, counts). */
export const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  PERSON_NAME: 'Person',
  DATE_OF_BIRTH: 'Geburtsdatum',
  OTHER_DATE: 'Datum',
  AGE: 'Alter',
  ADDRESS: 'Adresse',
  PHONE: 'Telefon',
  EMAIL: 'E-Mail',
  URL: 'URL',
  ID_NUMBER: 'ID-Nummer',
  ORGANIZATION: 'Organisation',
  PROFESSION: 'Beruf',
  OTHER_PII: 'Sonstige',
}

export function entityTypeLabel(type: string): string {
  return ENTITY_TYPE_LABELS[type as EntityType] ?? type
}

/** Entity status → German display name. */
export const ENTITY_STATUS_LABELS: Record<EntityStatus, string> = {
  REDACTED: 'Entfernt',
  GENERALIZED: 'Verallgemeinert',
  TAGGED: 'Getaggt',
  PRESERVED: 'Beibehalten',
}

export function entityStatusLabel(status: string): string {
  return ENTITY_STATUS_LABELS[status as EntityStatus] ?? status
}

/** Transformation → German display name (detail panel). */
export const TRANSFORMATION_LABELS: Record<TransformationType, string> = {
  TYPE_MASK: 'Typ-Maske',
  CONSISTENT_TAG: 'Konsistenter Platzhalter',
  GENERALIZE: 'Verallgemeinerung',
  REMOVE: 'Entfernung',
  PRESERVE: 'Beibehalten',
}

export function transformationLabel(transformation: string): string {
  return TRANSFORMATION_LABELS[transformation as TransformationType] ?? transformation
}

/** Validation status → German label + StatusBadge pill color. */
export const VALIDATION_STATUS_LABELS: Record<ValidationStatus, string> = {
  PASS: 'Bestanden',
  REVIEW_REQUIRED: 'Prüfung erforderlich',
  FAIL: 'Fehlgeschlagen',
}

export const VALIDATION_STATUS_COLORS: Record<ValidationStatus, string> = {
  PASS: 'green',
  REVIEW_REQUIRED: 'amber',
  FAIL: 'red',
}

export function validationStatusLabel(status: string): string {
  return VALIDATION_STATUS_LABELS[status as ValidationStatus] ?? status
}

export function validationStatusColor(status: string): string {
  return VALIDATION_STATUS_COLORS[status as ValidationStatus] ?? 'gray'
}

/** Warning severity → German label + pill color. */
export const SEVERITY_LABELS: Record<WarningSeverity, string> = {
  INFO: 'Hinweis',
  WARNING: 'Warnung',
  HIGH: 'Kritisch',
}

export const SEVERITY_COLORS: Record<WarningSeverity, string> = {
  INFO: 'blue',
  WARNING: 'amber',
  HIGH: 'red',
}

export function severityLabel(severity: string): string {
  return SEVERITY_LABELS[severity as WarningSeverity] ?? severity
}

export function severityColor(severity: string): string {
  return SEVERITY_COLORS[severity as WarningSeverity] ?? 'gray'
}

/**
 * Highlight classes for entity spans in the source-review view, by entity
 * status: REDACTED red-ish, GENERALIZED amber, TAGGED blue, PRESERVED gray
 * outline. Paired with a visible label chip in EntityHighlights.vue.
 */
export const ENTITY_HIGHLIGHT_CLASSES: Record<EntityStatus, string> = {
  REDACTED:
    'bg-red-100 text-red-900 ring-1 ring-red-300 dark:bg-red-900/40 dark:text-red-200 dark:ring-red-700',
  GENERALIZED:
    'bg-amber-100 text-amber-900 ring-1 ring-amber-300 dark:bg-amber-900/40 dark:text-amber-200 dark:ring-amber-700',
  TAGGED:
    'bg-blue-100 text-blue-900 ring-1 ring-blue-300 dark:bg-blue-900/40 dark:text-blue-200 dark:ring-blue-700',
  PRESERVED: 'bg-transparent text-content ring-1 ring-slate-400 dark:ring-slate-500',
}

export function entityHighlightClass(status: string): string {
  return ENTITY_HIGHLIGHT_CLASSES[status as EntityStatus] ?? ENTITY_HIGHLIGHT_CLASSES.PRESERVED
}

/** Highlight class for validation-warning locations (yellow). */
export const WARNING_HIGHLIGHT_CLASS =
  'bg-yellow-100 text-yellow-900 ring-1 ring-yellow-400 dark:bg-yellow-900/40 dark:text-yellow-200 dark:ring-yellow-600'

/** Small label chip inside a highlight, by entity status. */
export const ENTITY_CHIP_CLASSES: Record<EntityStatus, string> = {
  REDACTED: 'bg-red-200 text-red-900 dark:bg-red-800 dark:text-red-100',
  GENERALIZED: 'bg-amber-200 text-amber-900 dark:bg-amber-800 dark:text-amber-100',
  TAGGED: 'bg-blue-200 text-blue-900 dark:bg-blue-800 dark:text-blue-100',
  PRESERVED: 'bg-slate-200 text-slate-700 dark:bg-slate-600 dark:text-slate-100',
}

export function entityChipClass(status: string): string {
  return ENTITY_CHIP_CLASSES[status as EntityStatus] ?? ENTITY_CHIP_CLASSES.PRESERVED
}

/** StatusBadge pill color per entity status (legend, detail panel). */
export const ENTITY_STATUS_PILL_COLORS: Record<EntityStatus, string> = {
  REDACTED: 'red',
  GENERALIZED: 'amber',
  TAGGED: 'blue',
  PRESERVED: 'gray',
}

export function entityStatusPillColor(status: string): string {
  return ENTITY_STATUS_PILL_COLORS[status as EntityStatus] ?? 'gray'
}
