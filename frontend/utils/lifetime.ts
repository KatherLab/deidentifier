/**
 * How long the backend still holds a result, expressed for the review UI.
 *
 * The countdown is not decoration: while it runs, a copy of the document lives
 * in the server's memory. Showing it is how the app stays honest about that,
 * and the extension offered near the end is what keeps the window short for
 * everyone who is *not* still working.
 *
 * Pure functions only — the ticking lives in `composables/useResultLifetime.ts`.
 */
import { i18n, INTL_LOCALES, type SupportedLocale } from '@/i18n'

/** Below this many seconds the UI warns and offers an extension. */
export const EXPIRY_WARNING_SECONDS = 60

/**
 * Seconds left until `expiresAt` (epoch ms), never negative. Null when the
 * document has no result yet, i.e. there is nothing to count down.
 */
export function remainingSeconds(expiresAt: number | null, now: number): number | null {
  if (expiresAt === null) return null
  return Math.max(0, Math.ceil((expiresAt - now) / 1000))
}

const unitFormatters = new Map<string, Intl.NumberFormat>()

/** Cached `Intl` unit formatter — this runs on every tick of the countdown. */
function unit(value: number, name: 'hour' | 'minute' | 'second', locale: SupportedLocale): string {
  const key = `${locale}:${name}`
  let formatter = unitFormatters.get(key)
  if (formatter === undefined) {
    formatter = new Intl.NumberFormat(INTL_LOCALES[locale], {
      style: 'unit',
      unit: name,
      unitDisplay: 'short',
    })
    unitFormatters.set(key, formatter)
  }
  return formatter.format(value)
}

/**
 * The time left, in the largest unit that still tells the truth: "1 Std.",
 * "1 Std. 5 Min.", "45 Min.", "47 Sek.".
 *
 * `m:ss` was fine for a 15-minute window but reads as nonsense once an
 * extension buys an hour ("60:00"), and a clock format implies a precision
 * nobody needs at that range. Below a minute the seconds do matter — that is
 * when the warning is up — so they are shown then and only then. The unit
 * names come from `Intl`, which knows that German abbreviates minutes as
 * "Min." and French as "min".
 */
export function formatRemaining(seconds: number | null, locale?: SupportedLocale): string {
  if (seconds === null) return ''
  const active = locale ?? (i18n.global.locale.value as SupportedLocale)
  if (seconds < 60) return unit(seconds, 'second', active)
  if (seconds < 3600) return unit(Math.floor(seconds / 60), 'minute', active)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const hoursText = unit(hours, 'hour', active)
  return minutes === 0 ? hoursText : `${hoursText} ${unit(minutes, 'minute', active)}`
}

/** In the warning window: running out, but not out yet. */
export function isExpiring(seconds: number | null): boolean {
  return seconds !== null && seconds > 0 && seconds <= EXPIRY_WARNING_SECONDS
}

/** The server-side copy is gone (or is about to be swept). */
export function isExpired(seconds: number | null): boolean {
  return seconds === 0
}
