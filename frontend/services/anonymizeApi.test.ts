import { afterEach, describe, expect, it, vi } from 'vitest'
import { anonymizeApi, appendCustomRules, hasPolicyEntries } from '@/services/anonymizeApi'
import { api } from '@/services/api'

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

describe('forgetResult', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('deletes the cached detection by request id', async () => {
    const del = vi.spyOn(api, 'delete').mockResolvedValue({ status: 204 })

    await anonymizeApi.forgetResult('a b/c')

    expect(del).toHaveBeenCalledWith('/anonymize/a%20b%2Fc')
  })

  it('never rejects — a document is closing, not a user action to interrupt', async () => {
    vi.spyOn(api, 'delete').mockRejectedValue(new Error('offline'))

    await expect(anonymizeApi.forgetResult('abc')).resolves.toBeUndefined()
  })
})

describe('forgetResultOnUnload', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('uses keepalive, so the request survives the page going away', () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    anonymizeApi.forgetResultOnUnload('abc')

    expect(fetchMock).toHaveBeenCalledWith(`${api.defaults.baseURL}/anonymize/abc`, {
      method: 'DELETE',
      keepalive: true,
    })
    vi.unstubAllGlobals()
  })

  it('swallows a failing fetch during unload', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        throw new Error('unloading')
      }),
    )

    expect(() => anonymizeApi.forgetResultOnUnload('abc')).not.toThrow()
    vi.unstubAllGlobals()
  })
})
