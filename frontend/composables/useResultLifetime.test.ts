import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref, type Ref } from 'vue'
import { mount } from '@vue/test-utils'
import { useResultLifetime, type ResultLifetime } from '@/composables/useResultLifetime'
import { i18n } from '@/i18n'

/** Mount the composable in a real component so onUnmounted actually runs. */
function withLifetime(expiresAt: Ref<number | null>) {
  let api!: ResultLifetime
  const wrapper = mount(
    defineComponent({
      setup() {
        api = useResultLifetime(() => expiresAt.value)
        return () => h('div')
      },
    }),
  )
  return { api, wrapper }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-08-06T10:00:00Z'))
  // Pin the locale: the formatted text is locale-dependent and jsdom's
  // navigator language would otherwise decide what these assertions read.
  i18n.global.locale.value = 'de'
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useResultLifetime', () => {
  it('counts down once a second', async () => {
    const expiresAt = ref(Date.now() + 90_000)
    const { api, wrapper } = withLifetime(expiresAt)

    expect(api.formatted.value).toBe('1 Min.')
    expect(api.isExpiring.value).toBe(false)

    await vi.advanceTimersByTimeAsync(31_000)
    expect(api.formatted.value).toBe('59 Sek.')
    expect(api.isExpiring.value).toBe(true)
    expect(api.isExpired.value).toBe(false)

    await vi.advanceTimersByTimeAsync(59_000)
    expect(api.isExpired.value).toBe(true)
    expect(api.isExpiring.value).toBe(false)
    wrapper.unmount()
  })

  it('reads the deadline from the clock, so a suspended tab wakes up correct', async () => {
    const expiresAt = ref(Date.now() + 600_000)
    const { api, wrapper } = withLifetime(expiresAt)

    // The tab was frozen: no intervals fired, but nine minutes of wall-clock
    // time passed. A tick-counting countdown would still say 9:59.
    vi.setSystemTime(new Date('2026-08-06T10:09:00Z'))
    await vi.advanceTimersByTimeAsync(1000)

    expect(api.formatted.value).toBe('59 Sek.')
    wrapper.unmount()
  })

  it('follows a new deadline after an extension', async () => {
    const expiresAt = ref(Date.now() + 30_000)
    const { api, wrapper } = withLifetime(expiresAt)
    expect(api.isExpiring.value).toBe(true)

    expiresAt.value = Date.now() + 3_600_000 // the user pressed "Verlängern"
    await vi.advanceTimersByTimeAsync(1000)

    expect(api.isExpiring.value).toBe(false)
    expect(api.formatted.value).toBe('59 Min.')
    wrapper.unmount()
  })

  it('stops ticking when the view goes away', async () => {
    const expiresAt = ref(Date.now() + 60_000)
    const { wrapper } = withLifetime(expiresAt)
    const clearInterval = vi.spyOn(window, 'clearInterval')

    wrapper.unmount()

    expect(clearInterval).toHaveBeenCalled()
  })

  it('shows nothing while there is no result', () => {
    const { api, wrapper } = withLifetime(ref(null))

    expect(api.remaining.value).toBeNull()
    expect(api.formatted.value).toBe('')
    expect(api.isExpiring.value).toBe(false)
    expect(api.isExpired.value).toBe(false)
    wrapper.unmount()
  })
})
