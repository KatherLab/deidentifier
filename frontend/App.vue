<template>
  <div class="min-h-screen">
    <header class="border-b border-default">
      <div class="mx-auto flex items-center gap-3 px-4 py-4" :class="containerClass">
        <h1 class="text-xl font-semibold text-content">{{ t('app.title') }}</h1>

        <div class="ml-auto flex items-center gap-1.5">
          <!-- System hints (external endpoints / unready detectors): compact
               chip that opens a popover with the full details. -->
          <div v-if="systemHints.length > 0" ref="hintsContainer" class="relative">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 transition-colors hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300 dark:hover:bg-amber-900/40"
              :aria-expanded="hintsOpen"
              @click="toggleHints()"
            >
              <AlertTriangle class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {{ hintsLabel }}
            </button>
            <div
              v-if="hintsOpen"
              class="absolute right-0 top-full z-20 mt-2 w-80 rounded-card border border-default bg-surface p-3 shadow-lg"
              role="dialog"
              :aria-label="t('header.hints.dialog_label')"
            >
              <ul class="space-y-2 text-sm text-content">
                <li
                  v-for="(hint, index) in systemHints"
                  :key="index"
                  class="flex items-start gap-2"
                >
                  <AlertTriangle
                    class="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
                    aria-hidden="true"
                  />
                  <span>{{ hint }}</span>
                </li>
              </ul>
            </div>
          </div>

          <!-- Settings: expert-mode switch. -->
          <div ref="settingsContainer" class="relative">
            <button
              type="button"
              class="rounded-card p-2 text-content-subtle transition-colors hover:bg-surface-muted hover:text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              :aria-label="t('header.settings.label')"
              :aria-expanded="settingsOpen"
              @click="toggleSettings()"
            >
              <Settings class="h-5 w-5" aria-hidden="true" />
            </button>
            <div
              v-if="settingsOpen"
              class="absolute right-0 top-full z-20 mt-2 w-72 rounded-card border border-default bg-surface p-4 shadow-lg"
              role="dialog"
              :aria-label="t('header.settings.label')"
            >
              <div class="flex items-center justify-between gap-3">
                <span id="expert-mode-label" class="text-sm font-medium text-content">
                  {{ t('header.settings.expert_mode') }}
                </span>
                <button
                  type="button"
                  role="switch"
                  :aria-checked="settings.expertMode"
                  aria-labelledby="expert-mode-label"
                  class="relative h-5 w-9 shrink-0 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  :class="settings.expertMode ? 'bg-primary' : 'bg-slate-300 dark:bg-slate-600'"
                  @click="settings.setExpertMode(!settings.expertMode)"
                >
                  <span
                    class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform"
                    :class="settings.expertMode ? 'translate-x-4' : ''"
                    aria-hidden="true"
                  ></span>
                </button>
              </div>
              <p class="mt-1.5 text-xs text-content-subtle">
                {{ t('header.settings.expert_mode_hint') }}
              </p>
            </div>
          </div>

          <LanguageSwitcher />

          <!-- Dark mode -->
          <button
            type="button"
            class="rounded-card p-2 text-content-subtle transition-colors hover:bg-surface-muted hover:text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :aria-label="isDark ? t('header.theme.to_light') : t('header.theme.to_dark')"
            @click="toggleDarkMode"
          >
            <Sun v-if="isDark" class="h-5 w-5" aria-hidden="true" />
            <Moon v-else class="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>

    <main class="mx-auto px-4 py-8" :class="containerClass">
      <ResultView v-if="session.phase === 'result'" />
      <InputPanel v-else />
    </main>

    <ToastContainer />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, Moon, Settings, Sun } from '@lucide/vue'
import InputPanel from '@/components/anonymizer/InputPanel.vue'
import ResultView from '@/components/anonymizer/ResultView.vue'
import LanguageSwitcher from '@/components/common/LanguageSwitcher.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'
import { usePopover } from '@/composables/usePopover'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'

const { t } = useI18n()
const session = useSessionStore()
const settings = useSettingsStore()

const hintsContainer = ref<HTMLElement | null>(null)
const { open: hintsOpen, toggle: toggleHints } = usePopover(hintsContainer)

const settingsContainer = ref<HTMLElement | null>(null)
const { open: settingsOpen, toggle: toggleSettings } = usePopover(settingsContainer)

/** Full sentences for the popover; the header chip stays compact. */
const systemHints = computed<string[]>(() => {
  const hints: string[] = []
  for (const endpoint of session.externalEndpoints) {
    hints.push(t('header.hints.external_endpoint', { name: endpoint.name, host: endpoint.host }))
  }
  for (const detector of session.notReadyDetectors) {
    hints.push(t('header.hints.detector_not_ready', { name: detector.name }))
  }
  return hints
})

const hintsLabel = computed(() => {
  const external = session.externalEndpoints.length > 0
  const notReady = session.notReadyDetectors.length > 0
  if (external && !notReady) return t('header.hints.chip_external')
  if (!external && notReady) return t('header.hints.chip_detector')
  return t('header.hints.chip_count', { count: systemHints.value.length })
})

/**
 * The landing page stays narrow and centered; the result screen uses (nearly)
 * the full viewport width so side-by-side panels have room (96rem = the 2xl
 * breakpoint).
 */
const containerClass = computed(() => (session.phase === 'result' ? 'max-w-[96rem]' : 'max-w-4xl'))

// Dark mode (Tailwind class strategy). Only the theme preference is
// persisted — never any document content.
const isDark = ref(document.documentElement.classList.contains('dark'))

function toggleDarkMode() {
  isDark.value = !isDark.value
  document.documentElement.classList.toggle('dark', isDark.value)
  try {
    localStorage.setItem('darkMode', isDark.value ? '1' : '0')
  } catch {
    /* localStorage unavailable — theme just won't persist */
  }
}

onMounted(() => {
  void session.fetchStatus()
})
</script>
