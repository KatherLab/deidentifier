import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { i18n, type SupportedLocale } from './i18n'
import { applyLocale } from './composables/useLocale'
import './assets/main.css'

const app = createApp(App)
app.use(createPinia())
app.use(i18n)

// Load the detected locale's catalog (and set <html lang>) before mount so the
// first paint is already localized. The locale follows the browser language
// (see detectInitialLocale in i18n/index.ts) unless the user saved an explicit
// choice — auto-detection is not persisted, only an explicit switch is. German
// is bundled eagerly, so this resolves synchronously for German and after a
// small dynamic import for the other languages.
applyLocale(i18n.global.locale.value as SupportedLocale, false).finally(() => {
  app.mount('#app')
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled Promise Rejection:', event.reason)
})
