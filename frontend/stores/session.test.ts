import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSessionStore } from '@/stores/session'
import { applyLocale } from '@/composables/useLocale'

describe('output language', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await applyLocale('de', false)
  })

  it('follows the interface language until pinned', async () => {
    const session = useSessionStore()
    expect(session.outputLanguage).toBe('de')

    await applyLocale('en', false)
    expect(session.outputLanguage).toBe('en')
  })

  it('stays put once pinned, whatever the interface does', async () => {
    const session = useSessionStore()
    session.setOutputLanguage('fr')

    await applyLocale('en', false)
    expect(session.outputLanguage).toBe('fr')

    // Releasing the pin hands control back to the interface language.
    session.setOutputLanguage(null)
    expect(session.outputLanguage).toBe('en')
  })

  it('counts as a customized advanced setting only when it deviates', async () => {
    const session = useSessionStore()
    expect(session.advancedCustomized).toBe(false)

    // Pinning the language the UI already uses changes nothing about the run.
    session.setOutputLanguage('de')
    expect(session.advancedCustomized).toBe(false)

    session.setOutputLanguage('es')
    expect(session.advancedCustomized).toBe(true)
  })

  it('is cleared by the advanced-settings reset', () => {
    const session = useSessionStore()
    session.setOutputLanguage('es')

    session.resetAdvancedSettings()

    expect(session.outputLanguageOverride).toBeNull()
    expect(session.outputLanguage).toBe('de')
  })

  it('is captured per document at submit', () => {
    const session = useSessionStore()
    session.setOutputLanguage('fr')
    session.submitText('Ein Befund.')

    // The snapshot travels with the document: later UI/settings changes must
    // not rewrite the placeholders of a document that is already running.
    expect(session.documents.map((doc) => doc.outputLanguage)).toEqual(['fr'])
    session.setOutputLanguage('es')
    expect(session.documents[0]!.outputLanguage).toBe('fr')

    session.reset()
  })
})
