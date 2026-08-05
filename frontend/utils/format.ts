/**
 * Locale-aware number formatting.
 *
 * Percentages appear in progress bars, document chips and the entity detail
 * panel; the spacing before the sign and the decimal separator differ per
 * language ("75 %" in German and French, "75%" in English), so every one of
 * them goes through `Intl` rather than string concatenation.
 */
import { i18n } from '@/i18n'

/** A percentage given as 0–100, formatted for the active locale ("75 %"). */
export function formatPercent(percent: number): string {
  return i18n.global.n(percent / 100, 'percent')
}

/** A plain number with at most one decimal ("1,5" in German, "1.5" in English). */
export function formatDecimal(value: number): string {
  return i18n.global.n(value, 'decimal')
}
