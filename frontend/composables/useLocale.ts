// Locale management — mirrors the dark-mode pattern in App.vue: the active
// locale is persisted to localStorage and reflected on <html lang>. Non-default
// catalogs are lazy-loaded (dynamic import) so the initial bundle only ships
// the active language plus the eager German fallback.
import { computed } from 'vue'
import {
  i18n,
  persistLocale,
  SUPPORTED_LOCALES,
  type MessageSchema,
  type SupportedLocale,
} from '@/i18n'

// The German entry is never actually awaited (it is bundled eagerly and
// pre-marked as loaded below); it exists so the map stays exhaustive over
// SupportedLocale. Hence the build's INEFFECTIVE_DYNAMIC_IMPORT note for
// de.json — expected, and the same trade-off llmaixweb makes for `en`.
const messageLoaders: Record<SupportedLocale, () => Promise<{ default: MessageSchema }>> = {
  de: () => import('@/locales/de.json'),
  en: () => import('@/locales/en.json'),
  fr: () => import('@/locales/fr.json'),
  es: () => import('@/locales/es.json'),
}

// `de` is bundled eagerly by i18n/index.ts, so it starts out loaded.
const loaded = new Set<SupportedLocale>(['de'])

/**
 * Make a locale's catalog available without switching to it — the policy
 * editor previews the placeholders of the chosen OUTPUT language, which may
 * differ from the interface language.
 */
export async function loadLocaleMessages(locale: SupportedLocale): Promise<void> {
  if (loaded.has(locale)) return
  const mod = await messageLoaders[locale]()
  i18n.global.setLocaleMessage(locale, mod.default)
  loaded.add(locale)
}

/**
 * Load (if needed) and activate a locale.
 *
 * @param persist  whether to remember the choice (true for an explicit user
 *                 selection, false for boot-time auto-detection).
 */
export async function applyLocale(locale: SupportedLocale, persist = true): Promise<void> {
  await loadLocaleMessages(locale)
  i18n.global.locale.value = locale
  document.documentElement.setAttribute('lang', locale)
  if (persist) persistLocale(locale)
}

export function useLocale() {
  const locale = computed<SupportedLocale>(() => i18n.global.locale.value as SupportedLocale)

  return {
    locale,
    supportedLocales: SUPPORTED_LOCALES,
    setLocale: (next: SupportedLocale) => applyLocale(next, true),
  }
}
