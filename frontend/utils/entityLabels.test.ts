import { describe, expect, it } from 'vitest'
import {
  ENTITY_HIGHLIGHT_CLASSES,
  ENTITY_STATUS_LABELS,
  ENTITY_TYPE_DESCRIPTIONS,
  ENTITY_TYPE_LABELS,
  SEVERITY_COLORS,
  entityHighlightClass,
  entityStatusLabel,
  entityTypeLabel,
  severityColor,
  severityLabel,
  sourceTypeLabel,
  transformationLabel,
  validationStatusColor,
  validationStatusLabel,
} from '@/utils/entityLabels'
import { DEFAULT_POLICY } from '@/utils/policy'
import type { EntityType } from '@/types/anonymizer'

describe('label lookups', () => {
  it('translates the known vocabularies', () => {
    expect(entityTypeLabel('PERSON_NAME')).toBe(ENTITY_TYPE_LABELS.PERSON_NAME)
    expect(entityStatusLabel('REDACTED')).toBe(ENTITY_STATUS_LABELS.REDACTED)
    expect(sourceTypeLabel('pdf-ocr')).toBe('PDF (OCR)')
    expect(validationStatusLabel('PASS')).toBeTruthy()
    expect(severityLabel('HIGH')).toBe('Kritisch')
  })

  // A value the backend adds later must still render as something readable
  // rather than blanking the chip.
  it('falls back to the raw value for unknown keys', () => {
    expect(entityTypeLabel('NEW_TYPE')).toBe('NEW_TYPE')
    expect(entityStatusLabel('WEIRD')).toBe('WEIRD')
    expect(transformationLabel('SHIFT_DATE')).toBe('SHIFT_DATE')
    expect(sourceTypeLabel('rtf')).toBe('rtf')
  })

  it('falls back to a neutral color for unknown keys', () => {
    expect(validationStatusColor('UNKNOWN')).toBe('gray')
    expect(severityColor('UNKNOWN')).toBe('gray')
    expect(entityHighlightClass('UNKNOWN')).toBe(ENTITY_HIGHLIGHT_CLASSES.PRESERVED)
  })
})

describe('vocabulary coverage', () => {
  // DEFAULT_POLICY is keyed by the full EntityType union, so it is the
  // authoritative list of types the UI must be able to render.
  it('labels and describes every entity type', () => {
    for (const type of Object.keys(DEFAULT_POLICY) as EntityType[]) {
      expect(ENTITY_TYPE_LABELS[type], type).toBeTruthy()
      expect(ENTITY_TYPE_DESCRIPTIONS[type], type).toBeTruthy()
    }
  })

  it('gives every entity status its own highlight class', () => {
    const classes = Object.values(ENTITY_HIGHLIGHT_CLASSES)
    expect(new Set(classes).size).toBe(classes.length)
  })

  it('escalates severity colors from info to critical', () => {
    expect(SEVERITY_COLORS.INFO).toBe('blue')
    expect(SEVERITY_COLORS.WARNING).toBe('amber')
    expect(SEVERITY_COLORS.HIGH).toBe('red')
  })
})
