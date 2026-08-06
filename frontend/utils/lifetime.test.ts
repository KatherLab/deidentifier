import { describe, expect, it } from 'vitest'
import {
  EXPIRY_WARNING_SECONDS,
  formatRemaining,
  isExpired,
  isExpiring,
  remainingSeconds,
} from '@/utils/lifetime'

describe('remainingSeconds', () => {
  it('is null without a deadline — nothing to count down', () => {
    expect(remainingSeconds(null, 1_000_000)).toBeNull()
  })

  it('rounds up, so the last second is shown as 1 rather than 0', () => {
    expect(remainingSeconds(1_000_500, 1_000_000)).toBe(1)
  })

  it('never goes negative once the deadline has passed', () => {
    expect(remainingSeconds(1_000_000, 1_060_000)).toBe(0)
  })
})

describe('formatRemaining', () => {
  it('shows seconds only in the final minute, where they matter', () => {
    expect(formatRemaining(47, 'de')).toBe('47 Sek.')
    expect(formatRemaining(9, 'de')).toBe('9 Sek.')
    expect(formatRemaining(0, 'de')).toBe('0 Sek.')
  })

  it('shows whole minutes below an hour', () => {
    expect(formatRemaining(60, 'de')).toBe('1 Min.')
    expect(formatRemaining(119, 'de')).toBe('1 Min.') // floors, so it counts down
    expect(formatRemaining(724, 'de')).toBe('12 Min.')
    expect(formatRemaining(3599, 'de')).toBe('59 Min.')
  })

  it('shows hours once there are any — never "60:00"', () => {
    expect(formatRemaining(3600, 'de')).toBe('1 Std.')
    expect(formatRemaining(3900, 'de')).toBe('1 Std. 5 Min.')
    expect(formatRemaining(12 * 3600, 'de')).toBe('12 Std.')
  })

  it('uses each language’s own unit names', () => {
    // French separates the number from the unit with a non-breaking space,
    // which is right but not worth pinning byte-for-byte across ICU versions.
    const spaces = (text: string) => text.replace(/[\u202f\u00a0]/g, ' ')

    expect(formatRemaining(3900, 'en')).toBe('1 hr 5 mins')
    expect(spaces(formatRemaining(3900, 'fr'))).toBe('1 h 5 min')
    expect(formatRemaining(3900, 'es')).toBe('1 h 5 min')
    expect(spaces(formatRemaining(47, 'fr'))).toBe('47 s')
  })

  it('is empty when there is nothing to show', () => {
    expect(formatRemaining(null, 'de')).toBe('')
  })
})

describe('isExpiring / isExpired', () => {
  it('warns inside the final window only', () => {
    expect(isExpiring(EXPIRY_WARNING_SECONDS + 1)).toBe(false)
    expect(isExpiring(EXPIRY_WARNING_SECONDS)).toBe(true)
    expect(isExpiring(1)).toBe(true)
  })

  it('stops warning once it is actually gone — that is a different message', () => {
    expect(isExpiring(0)).toBe(false)
    expect(isExpired(0)).toBe(true)
    expect(isExpired(1)).toBe(false)
  })

  it('says nothing at all without a deadline', () => {
    expect(isExpiring(null)).toBe(false)
    expect(isExpired(null)).toBe(false)
  })
})
