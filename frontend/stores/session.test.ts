import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSessionStore, type SessionDocument } from '@/stores/session'
import { applyLocale } from '@/composables/useLocale'
import { i18n } from '@/i18n'
import { anonymizeApi } from '@/services/anonymizeApi'
import { useToastStore } from '@/stores/toast'
import type { AnonymizeResponse } from '@/types/anonymizer'

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

describe('result lifetime', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-06T10:00:00Z'))
    i18n.global.locale.value = 'de' // the toast text is locale-dependent
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  /**
   * A batch whose documents already carry results, as after a finished run.
   * One `submitText`/`submitFiles` call per batch — a second submit would
   * replace the first batch rather than add to it.
   */
  function batchWithResults(
    session: ReturnType<typeof useSessionStore>,
    ids: string[],
  ): SessionDocument[] {
    session.submitFiles(ids.map((id) => new File(['Ein Befund.'], `${id}.txt`)))
    session.documents.forEach((doc, index) => {
      doc.result = {
        request_id: ids[index]!,
        lifetime: { expires_in_seconds: 30, can_extend: true },
      } as AnonymizeResponse
      doc.expiresAt = Date.now() + 30_000
      doc.canExtend = true
    })
    return session.documents
  }

  it('extends every document of the batch, not just the active one', async () => {
    const session = useSessionStore()
    batchWithResults(session, ['req-1', 'req-2'])
    const extend = vi.spyOn(anonymizeApi, 'extendResult').mockResolvedValue({
      data: { expires_in_seconds: 900, can_extend: true },
    } as never)

    await session.extendResults()

    expect(extend.mock.calls.map((call) => call[0]).sort()).toEqual(['req-1', 'req-2'])
    for (const doc of session.documents) {
      expect(doc.expiresAt).toBe(Date.now() + 900_000)
      expect(doc.canExtend).toBe(true)
      expect(doc.extending).toBe(false)
    }
    session.reset()
  })

  it('reports the ceiling instead of pretending the click worked', async () => {
    const session = useSessionStore()
    batchWithResults(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockResolvedValue({
      data: { expires_in_seconds: 120, can_extend: false },
    } as never)

    await session.extendResults()

    expect(session.documents[0]!.canExtend).toBe(false)
    expect(session.documents[0]!.expiresAt).toBe(Date.now() + 120_000)
    session.reset()
  })

  it('marks a document expired when the backend has already forgotten it', async () => {
    const session = useSessionStore()
    batchWithResults(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockRejectedValue(new Error('410'))

    await session.extendResults()

    expect(session.documents[0]!.expiresAt).toBe(Date.now())
    expect(session.documents[0]!.canExtend).toBe(false)
    session.reset()
  })

  it('does nothing when no document has a result yet', async () => {
    const session = useSessionStore()
    const extend = vi.spyOn(anonymizeApi, 'extendResult')

    await session.extendResults()

    expect(extend).not.toHaveBeenCalled()
  })
})

describe('batch-wide result lifetime', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-06T10:00:00Z'))
    i18n.global.locale.value = 'de' // the toast text is locale-dependent
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  function batch(session: ReturnType<typeof useSessionStore>, ids: string[]): SessionDocument[] {
    session.submitFiles(ids.map((id) => new File(['Ein Befund.'], `${id}.txt`)))
    session.documents.forEach((doc, index) => {
      doc.result = { request_id: ids[index]! } as AnonymizeResponse
      doc.expiresAt = Date.now() + 900_000
      doc.canExtend = true
    })
    return session.documents
  }

  it('reports nothing to count down before the first result', () => {
    const session = useSessionStore()

    expect(session.resultsExpireAt).toBeNull()
    expect(session.resultsCanExtend).toBe(false)
  })

  it('counts down to the FIRST document that expires', () => {
    const session = useSessionStore()
    const docs = batch(session, ['req-1', 'req-2'])
    docs[1]!.expiresAt = Date.now() + 120_000 // this one dies first

    expect(session.resultsExpireAt).toBe(Date.now() + 120_000)
    session.reset()
  })

  it('offers extending while any document still has headroom', () => {
    const session = useSessionStore()
    const docs = batch(session, ['req-1', 'req-2'])
    docs[0]!.canExtend = false

    expect(session.resultsCanExtend).toBe(true)

    docs[1]!.canExtend = false
    expect(session.resultsCanExtend).toBe(false)
    session.reset()
  })

  it('confirms a successful extension, so stepping away is safe', async () => {
    const session = useSessionStore()
    batch(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockResolvedValue({
      data: { expires_in_seconds: 900, can_extend: true },
    } as never)
    const toast = useToastStore()

    await session.extendResults()

    expect(toast.toasts.at(-1)).toMatchObject({ type: 'success' })
    expect(toast.toasts.at(-1)!.message).toContain('15 Min.')
    session.reset()
  })

  it('says so when the ceiling was reached instead of claiming success', async () => {
    const session = useSessionStore()
    batch(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockResolvedValue({
      data: { expires_in_seconds: 300, can_extend: false },
    } as never)
    const toast = useToastStore()

    await session.extendResults()

    expect(toast.toasts.at(-1)).toMatchObject({ type: 'info' })
    session.reset()
  })

  it('reports an extension that came too late', async () => {
    const session = useSessionStore()
    batch(session, ['req-1'])
    vi.spyOn(anonymizeApi, 'extendResult').mockRejectedValue(new Error('410'))
    const toast = useToastStore()

    await session.extendResults()

    expect(toast.toasts.at(-1)).toMatchObject({ type: 'error' })
    session.reset()
  })
})
