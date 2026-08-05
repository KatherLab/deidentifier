import { describe, expect, it } from 'vitest'
import {
  ENTITY_HIGHLIGHT_CLASSES,
  ENTITY_STATUSES,
  ENTITY_TYPES,
  SEVERITY_COLORS,
  entityHighlightClass,
  entityStatusLabel,
  entityTypeDescription,
  entityTypeLabel,
  severityColor,
  severityLabel,
  sourceTypeLabel,
  transformationLabel,
  validationStatusColor,
  validationStatusLabel,
} from '@/utils/entityLabels'
import { DEFAULT_POLICY } from '@/utils/policy'
import de from '@/locales/de.json'
import type { EntityType } from '@/types/anonymizer'

describe('label lookups', () => {
  // Only the German catalog is bundled eagerly, and it is the fallback for
  // every locale, so an unswitched spec renders German.
  it('translates the known vocabularies', () => {
    expect(entityTypeLabel('PERSON_NAME')).toBe('Person')
    expect(entityStatusLabel('REDACTED')).toBe('Entfernt')
    expect(sourceTypeLabel('pdf-ocr')).toBe('PDF (OCR)')
    expect(validationStatusLabel('PASS')).toBe('Bestanden')
    expect(severityLabel('HIGH')).toBe('Kritisch')
  })

  // A value the backend adds later must still render as something readable
  // rather than blanking the chip or showing a raw catalog key.
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
  it('lists every entity type in the display order', () => {
    expect([...ENTITY_TYPES].sort()).toEqual((Object.keys(DEFAULT_POLICY) as EntityType[]).sort())
  })

  // A type missing from the catalog would silently render its raw enum value
  // ("ID_NUMBER"), which is why coverage is asserted against the catalog
  // itself rather than against the rendered label (a few, like URL, are
  // legitimately identical to their enum value).
  it('labels and describes every entity type', () => {
    for (const type of ENTITY_TYPES) {
      expect(de.entity.type, type).toHaveProperty(type)
      expect(de.entity.type_description, type).toHaveProperty(type)
      expect(entityTypeLabel(type), type).toBeTruthy()
      expect(entityTypeDescription(type), type).toBeTruthy()
    }
  })

  it('labels every entity status', () => {
    for (const status of ENTITY_STATUSES) {
      expect(de.entity.status, status).toHaveProperty(status)
      expect(entityStatusLabel(status), status).not.toBe(status)
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
