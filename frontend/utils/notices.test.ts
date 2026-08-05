import { afterEach, describe, expect, it } from 'vitest'
import { noticeMessage } from '@/utils/notices'
import { applyLocale } from '@/composables/useLocale'
import type { Notice, ValidationWarning } from '@/types/anonymizer'

function notice(code: string, params: Notice['params'] = {}): Notice {
  return { code, message: 'English fallback text.', params }
}

afterEach(async () => {
  await applyLocale('de', false)
})

describe('noticeMessage', () => {
  it('renders a known code from the catalog', () => {
    expect(noticeMessage(notice('ocr_recognition_errors'))).toContain('Texterkennung')
  })

  it('localizes an entity type inside the message', () => {
    const message = noticeMessage(notice('residual_identifier', { entity_type: 'EMAIL' }))

    expect(message).toContain('E-Mail')
    expect(message).not.toContain('EMAIL')
  })

  it('localizes the risk level of the re-check assessment', () => {
    expect(noticeMessage(notice('recheck_risk', { risk: 'high' }))).toContain('hoch')
  })

  it('keeps free params verbatim', () => {
    expect(noticeMessage(notice('pdf_docling_fallback', { reason: 'timeout' }))).toContain(
      'timeout',
    )
  })

  // The backend may gain a warning before the catalogs do — its English text is
  // still better than a raw key or an empty line.
  it('falls back to the backend message for an unknown code', () => {
    expect(noticeMessage(notice('brand_new_backend_code'))).toBe('English fallback text.')
  })

  // LLM re-check concerns are authored by the model itself and carry no code.
  it('falls back to the backend message when there is no code', () => {
    expect(noticeMessage(notice(''))).toBe('English fallback text.')
  })

  it('translates validation warnings the same way', () => {
    const warning: ValidationWarning = {
      category: 'revalidation_hit',
      message: 'A rule detector still finds a possible PHONE in the output.',
      severity: 'WARNING',
      start: 4,
      end: 9,
      code: 'revalidation_hit',
      params: { entity_type: 'PHONE' },
    }

    expect(noticeMessage(warning)).toContain('Telefon')
  })

  it('follows the active locale', async () => {
    await applyLocale('en', false)

    expect(noticeMessage(notice('residual_identifier', { entity_type: 'EMAIL' }))).toContain(
      'Redacted content of type Email',
    )
  })
})
