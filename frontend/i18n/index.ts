// vue-i18n setup — the single i18n instance used across the app.
//
// Follows llmaixweb's setup, with one deliberate difference: the source-of-
// truth catalog is GERMAN. The UI text of this app was authored in German for
// German clinical documents, so `de.json` is the catalog every other locale is
// checked against (scripts/i18n-check.mjs) and the fallback for any key a
// translation is missing.
//
// The full ("esm-bundler") vue-i18n build is aliased in vite.config.ts /
// vitest.config.ts so message strings compile at runtime without a separate
// precompile plugin. If bundle size becomes a concern,
// `@intlify/unplugin-vue-i18n` can precompile the catalogs and the alias can be
// dropped — no call-site changes required.
//
// `de` is bundled eagerly as the fallback; the other locales are lazy-loaded
// on demand (see composables/useLocale.ts).
import { createI18n } from 'vue-i18n'
import de from '@/locales/de.json'

export const SUPPORTED_LOCALES = ['de', 'en', 'fr', 'es'] as const
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number]

export const DEFAULT_LOCALE: SupportedLocale = 'de'

/** BCP-47 tags used for Intl date/number formatting per app locale. */
export const INTL_LOCALES: Record<SupportedLocale, string> = {
  de: 'de-DE',
  en: 'en-GB',
  fr: 'fr-FR',
  es: 'es-ES',
}

const STORAGE_KEY = 'locale'

/** The message-catalog shape; every locale must mirror `de.json`. */
export type MessageSchema = typeof de

function isSupported(value: string | null | undefined): value is SupportedLocale {
  return !!value && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

/**
 * Resolve the initial locale: an explicit saved choice wins, then the browser
 * language (matched on its primary subtag), then German.
 */
export function detectInitialLocale(): SupportedLocale {
  // Guard the browser globals: this runs at module-load time (via the
  // `createI18n` call below), which may happen in non-DOM contexts (e.g. a
  // test worker whose environment lacks `localStorage`/`navigator`).
  const saved = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
  if (isSupported(saved)) return saved

  const navLang =
    typeof navigator !== 'undefined' ? (navigator.language || '').slice(0, 2).toLowerCase() : ''
  if (isSupported(navLang)) return navLang

  return DEFAULT_LOCALE
}

/**
 * Persist an explicit language choice. Only a UI preference — never anything
 * derived from a document (see the privacy rule in stores/session.ts).
 */
export function persistLocale(locale: SupportedLocale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    /* localStorage unavailable — the choice just won't persist */
  }
}

// Shared Intl format presets, applied to every supported locale so `$n`
// renders consistently. Separators and the percent sign's spacing adapt to the
// active locale ("75 %" in German, "75%" in English).
const numberFormats = {
  decimal: { style: 'decimal', maximumFractionDigits: 1 },
  percent: { style: 'percent', maximumFractionDigits: 0 },
} as const

const perLocale = <T>(value: T): Record<SupportedLocale, T> =>
  Object.fromEntries(SUPPORTED_LOCALES.map((l) => [l, value])) as Record<SupportedLocale, T>

export const i18n = createI18n({
  legacy: false,
  // Expose $t/$n in every template without a per-component import.
  globalInjection: true,
  locale: detectInitialLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { de },
  numberFormats: perLocale(numberFormats),
})

/**
 * Translate outside of a component (stores, utils, services). Components use
 * `useI18n()` so their text re-renders on a language switch.
 */
export const t = i18n.global.t

/** True when the active catalog (or the German fallback) knows a key. */
export function hasMessage(key: string): boolean {
  return i18n.global.te(key) || i18n.global.te(key, DEFAULT_LOCALE)
}
