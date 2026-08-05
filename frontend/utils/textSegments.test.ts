import { describe, expect, it } from 'vitest'
import { buildHighlightSegments } from '@/utils/textSegments'
import type { AnonymizedEntity, ValidationWarning } from '@/types/anonymizer'

function entity(start: number, end: number, text: string): AnonymizedEntity {
  return {
    start,
    end,
    text,
    entity_type: 'PERSON_NAME',
    confidence: 1,
    detector: 'mock',
    transformation: 'CONSISTENT_TAG',
    replacement: '[PERSON_1]',
    status: 'TAGGED',
  }
}

function warning(start: number | null, end: number | null): ValidationWarning {
  return {
    category: 'residual_identifier',
    message: 'Rest',
    severity: 'HIGH',
    start,
    end,
    code: 'residual_identifier',
    params: { entity_type: 'PERSON_NAME' },
  }
}

describe('buildHighlightSegments', () => {
  it('splits the source into plain and entity segments', () => {
    const segments = buildHighlightSegments(
      'Hallo Max Mustermann!',
      [entity(6, 20, 'Max Mustermann')],
      [],
    )

    expect(segments.map((s) => s.text)).toEqual(['Hallo ', 'Max Mustermann', '!'])
    expect(segments.map((s) => s.entityIndex)).toEqual([null, 0, null])
  })

  it('covers the whole source text exactly once', () => {
    const source = 'A Max Mustermann B Erika Musterfrau C'
    const segments = buildHighlightSegments(
      source,
      [entity(2, 16, 'Max Mustermann'), entity(19, 35, 'Erika Musterfrau')],
      [warning(0, 1)],
    )

    expect(segments.map((s) => s.text).join('')).toBe(source)
  })

  it('uses code point offsets, not UTF-16 code units', () => {
    // The emoji is one code point but two UTF-16 units: a naive String.slice
    // would shift the entity by one and cut the emoji in half.
    const source = '🩺 Max'
    const segments = buildHighlightSegments(source, [entity(2, 5, 'Max')], [])

    const highlighted = segments.find((s) => s.entityIndex === 0)
    expect(highlighted?.text).toBe('Max')
    expect(segments.map((s) => s.text).join('')).toBe(source)
  })

  it('marks warning coverage independently of entities', () => {
    const segments = buildHighlightSegments('Patient: unbekannt', [], [warning(9, 18)])

    expect(segments.filter((s) => s.warning).map((s) => s.text)).toEqual(['unbekannt'])
  })

  it('splits an entity where a warning covers only part of it', () => {
    const segments = buildHighlightSegments(
      'Max Mustermann',
      [entity(0, 14, 'Max Mustermann')],
      [warning(0, 3)],
    )

    expect(segments).toHaveLength(2)
    expect(segments[0]).toMatchObject({ text: 'Max', entityIndex: 0, warning: true })
    expect(segments[1]).toMatchObject({ text: ' Mustermann', entityIndex: 0, warning: false })
  })

  it('renders the entity label chip exactly once, on the last segment', () => {
    const segments = buildHighlightSegments(
      'Max Mustermann',
      [entity(0, 14, 'Max Mustermann')],
      [warning(0, 3)],
    )

    expect(segments.filter((s) => s.showEntityLabel)).toHaveLength(1)
    expect(segments[segments.length - 1]?.showEntityLabel).toBe(true)
  })

  it('ignores unlocated warnings and empty spans', () => {
    const segments = buildHighlightSegments('Kurztext', [entity(3, 3, '')], [warning(null, null)])

    expect(segments).toEqual([
      expect.objectContaining({ text: 'Kurztext', entityIndex: null, warning: false }),
    ])
  })

  it('clamps offsets that exceed the source length', () => {
    const segments = buildHighlightSegments('Max', [entity(0, 99, 'Max')], [])

    expect(segments.map((s) => s.text).join('')).toBe('Max')
    expect(segments[0]?.entityIndex).toBe(0)
  })

  it('returns no segments for empty source text', () => {
    expect(buildHighlightSegments('', [], [])).toEqual([])
  })
})
