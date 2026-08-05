import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSettingsStore } from '@/stores/settings'

describe('settings store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('defaults both preferences to off', () => {
    const settings = useSettingsStore()

    expect(settings.expertMode).toBe(false)
    expect(settings.keepFilenames).toBe(false)
  })

  it('persists the preferences', () => {
    const settings = useSettingsStore()
    settings.setExpertMode(true)
    settings.setKeepFilenames(true)

    expect(localStorage.getItem('expertMode')).toBe('1')
    expect(localStorage.getItem('keepFilenames')).toBe('1')
  })

  it('restores persisted preferences on a fresh store', () => {
    localStorage.setItem('expertMode', '1')
    setActivePinia(createPinia())

    expect(useSettingsStore().expertMode).toBe(true)
  })

  // Private-browsing modes throw on localStorage access; the preference must
  // degrade to "not persisted" rather than breaking the app.
  it('survives an unavailable localStorage', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    setActivePinia(createPinia())

    const settings = useSettingsStore()
    expect(settings.expertMode).toBe(false)
    expect(() => settings.setExpertMode(true)).not.toThrow()
    expect(settings.expertMode).toBe(true)
  })
})
