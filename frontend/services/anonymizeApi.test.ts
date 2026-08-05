import { describe, expect, it } from 'vitest'
import { appendCustomRules, hasPolicyEntries } from '@/services/anonymizeApi'

describe('hasPolicyEntries', () => {
  it('is false for null, undefined and an empty map', () => {
    expect(hasPolicyEntries(null)).toBe(false)
    expect(hasPolicyEntries(undefined)).toBe(false)
    expect(hasPolicyEntries({})).toBe(false)
  })

  it('is true once a deviation is present', () => {
    expect(hasPolicyEntries({ OTHER_DATE: 'TYPE_MASK' })).toBe(true)
  })
})

describe('appendCustomRules', () => {
  it('omits every field when there are no rules', () => {
    const formData = new FormData()
    appendCustomRules(formData, null)

    expect([...formData.keys()]).toEqual([])
  })

  it('omits empty fields individually', () => {
    const formData = new FormData()
    appendCustomRules(formData, {
      customInstruction: '',
      redactTerms: ['Sonnenklinik'],
      preserveTerms: [],
    })

    expect([...formData.keys()]).toEqual(['redact_terms'])
  })

  it('sends the term lists as JSON arrays and the instruction as plain text', () => {
    const formData = new FormData()
    appendCustomRules(formData, {
      customInstruction: 'Auch Studien-IDs schwärzen.',
      redactTerms: ['Sonnenklinik', 'Station 4B'],
      preserveTerms: ['Cholezystitis'],
    })

    expect(formData.get('custom_instruction')).toBe('Auch Studien-IDs schwärzen.')
    expect(formData.get('redact_terms')).toBe('["Sonnenklinik","Station 4B"]')
    expect(formData.get('preserve_terms')).toBe('["Cholezystitis"]')
  })
})
