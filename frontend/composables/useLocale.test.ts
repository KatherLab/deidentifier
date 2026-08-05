import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { applyLocale, useLocale } from '@/composables/useLocale'
import { detectInitialLocale, i18n, SUPPORTED_LOCALES } from '@/i18n'
import { formatPercent } from '@/utils/format'

afterEach(async () => {
  localStorage.clear()
  await applyLocale('de', false)
})

describe('detectInitialLocale', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('prefers an explicitly saved choice', () => {
    localStorage.setItem('locale', 'fr')

    expect(detectInitialLocale()).toBe('fr')
  })

  it('falls back to the browser language', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('es-ES')

    expect(detectInitialLocale()).toBe('es')
  })

  it('defaults to German for an unsupported browser language', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('it-IT')

    expect(detectInitialLocale()).toBe('de')
  })

  it('ignores an unsupported saved value', () => {
    localStorage.setItem('locale', 'klingon')
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('en-GB')

    expect(detectInitialLocale()).toBe('en')
  })
})

describe('applyLocale', () => {
  it('loads the catalog, switches the app and sets <html lang>', async () => {
    await applyLocale('fr', false)

    expect(i18n.global.locale.value).toBe('fr')
    expect(document.documentElement.getAttribute('lang')).toBe('fr')
    expect(i18n.global.t('input.submit')).toBe('Anonymiser')
  })

  it('persists an explicit choice only', async () => {
    await applyLocale('en', false)
    expect(localStorage.getItem('locale')).toBeNull()

    await applyLocale('en', true)
    expect(localStorage.getItem('locale')).toBe('en')
  })

  it('exposes every supported locale through the composable', () => {
    expect(useLocale().supportedLocales).toEqual(SUPPORTED_LOCALES)
  })
})

describe('locale-aware formatting', () => {
  it('formats percentages the way each language writes them', async () => {
    // German (and French) put a non-breaking space before the sign, English
    // does not — hence Intl rather than string concatenation.
    expect(formatPercent(75).replace(/\s/gu, ' ')).toBe('75 %')

    await applyLocale('en', false)
    expect(formatPercent(75)).toBe('75%')
  })
})
