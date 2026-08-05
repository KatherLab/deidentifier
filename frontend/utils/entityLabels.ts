/**
 * Display names + visual treatment for entity types, entity statuses,
 * transformations, validation statuses and warning severities.
 *
 * The text lives in the message catalogs (`entity.*`, `validation.*`); the
 * functions here resolve a backend enum value to its localized label and fall
 * back to the raw value for anything a catalog does not know (a new backend
 * enum value must never blank the UI).
 *
 * Accessibility rule: highlight colors are ALWAYS paired with a visible text
 * label (chip) — never color alone.
 */
import { hasMessage, t } from '@/i18n'
import type {
  EntityStatus,
  EntityType,
  ValidationStatus,
  WarningSeverity,
} from '@/types/anonymizer'

/** Label for `key`, or the raw value when the catalogs don't know it. */
function label(key: string, value: string): string {
  return hasMessage(key) ? t(key) : value
}

export function sourceTypeLabel(type: string): string {
  return label(`entity.source_type.${type}`, type)
}

/**
 * All entity types in display order (policy editor rows, type dropdown).
 * Mirrors the backend's EntityType enum.
 */
export const ENTITY_TYPES: EntityType[] = [
  'PERSON_NAME',
  'DATE_OF_BIRTH',
  'OTHER_DATE',
  'AGE',
  'ADDRESS',
  'PHONE',
  'EMAIL',
  'URL',
  'ID_NUMBER',
  'ORGANIZATION',
  'PROFESSION',
  'OTHER_PII',
]

export function entityTypeLabel(type: string): string {
  return label(`entity.type.${type}`, type)
}

/** Short description of an entity type (policy editor rows). */
export function entityTypeDescription(type: EntityType): string {
  return label(`entity.type_description.${type}`, type)
}

/** Entity statuses in legend order. */
export const ENTITY_STATUSES: EntityStatus[] = ['REDACTED', 'GENERALIZED', 'TAGGED', 'PRESERVED']

export function entityStatusLabel(status: string): string {
  return label(`entity.status.${status}`, status)
}

export function transformationLabel(transformation: string): string {
  return label(`entity.transformation.${transformation}`, transformation)
}

export function validationStatusLabel(status: string): string {
  return label(`validation.status.${status}`, status)
}

export const VALIDATION_STATUS_COLORS: Record<ValidationStatus, string> = {
  PASS: 'green',
  REVIEW_REQUIRED: 'amber',
  FAIL: 'red',
}

export function validationStatusColor(status: string): string {
  return VALIDATION_STATUS_COLORS[status as ValidationStatus] ?? 'gray'
}

export function severityLabel(severity: string): string {
  return label(`validation.severity.${severity}`, severity)
}

export const SEVERITY_COLORS: Record<WarningSeverity, string> = {
  INFO: 'blue',
  WARNING: 'amber',
  HIGH: 'red',
}

export function severityColor(severity: string): string {
  return SEVERITY_COLORS[severity as WarningSeverity] ?? 'gray'
}

/**
 * Highlight classes for entity marks in the source-review view, by entity
 * status: REDACTED red-ish, GENERALIZED amber, TAGGED blue, PRESERVED neutral
 * outline. Subtle tinted background with a thin ring on hover; selection adds
 * a strong ring in EntityHighlights.vue. Never color alone — every mark also
 * carries a text tooltip/aria label.
 */
export const ENTITY_HIGHLIGHT_CLASSES: Record<EntityStatus, string> = {
  REDACTED:
    'bg-red-100 text-red-900 hover:ring-1 hover:ring-red-400 dark:bg-red-900/40 dark:text-red-200 dark:hover:ring-red-600',
  GENERALIZED:
    'bg-amber-100 text-amber-900 hover:ring-1 hover:ring-amber-400 dark:bg-amber-900/40 dark:text-amber-200 dark:hover:ring-amber-600',
  TAGGED:
    'bg-blue-100 text-blue-900 hover:ring-1 hover:ring-blue-400 dark:bg-blue-900/40 dark:text-blue-200 dark:hover:ring-blue-600',
  PRESERVED:
    'bg-transparent text-content ring-1 ring-slate-400 hover:ring-slate-600 dark:ring-slate-500 dark:hover:ring-slate-300',
}

export function entityHighlightClass(status: string): string {
  return ENTITY_HIGHLIGHT_CLASSES[status as EntityStatus] ?? ENTITY_HIGHLIGHT_CLASSES.PRESERVED
}

/** Highlight class for validation-warning locations (yellow). */
export const WARNING_HIGHLIGHT_CLASS =
  'bg-yellow-100 text-yellow-900 ring-1 ring-yellow-400 dark:bg-yellow-900/40 dark:text-yellow-200 dark:ring-yellow-600'

/** Compact legend dot per entity status (always paired with a text label). */
export const ENTITY_DOT_CLASSES: Record<EntityStatus, string> = {
  REDACTED: 'bg-red-400 dark:bg-red-500',
  GENERALIZED: 'bg-amber-400 dark:bg-amber-500',
  TAGGED: 'bg-blue-400 dark:bg-blue-500',
  PRESERVED: 'bg-transparent ring-1 ring-inset ring-slate-400 dark:ring-slate-500',
}

/** Legend dot for validation-warning locations. */
export const WARNING_DOT_CLASS = 'bg-yellow-400 dark:bg-yellow-500'

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
