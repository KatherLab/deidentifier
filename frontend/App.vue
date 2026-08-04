<template>
  <div class="min-h-screen">
    <!-- External-endpoint banner (dismissible) -->
    <div
      v-if="session.showExternalBanner"
      class="flex items-start gap-3 px-4 py-3 text-sm bg-amber-50 border-b border-amber-200 text-amber-800 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-300"
      role="alert"
    >
      <AlertTriangle class="h-5 w-5 shrink-0 mt-0.5" aria-hidden="true" />
      <p class="flex-1">
        Dokumentinhalte werden an einen externen Endpunkt gesendet:
        {{ externalEndpointsLabel }}
      </p>
      <button
        type="button"
        class="shrink-0 p-1 rounded-card hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
        aria-label="Hinweis schließen"
        @click="session.dismissExternalBanner()"
      >
        <X class="h-4 w-4" aria-hidden="true" />
      </button>
    </div>

    <!-- Detector-not-ready banner (enabled but unconfigured detectors) -->
    <div
      v-if="session.notReadyDetectors.length > 0"
      class="flex items-start gap-3 px-4 py-3 text-sm bg-amber-50 border-b border-amber-200 text-amber-800 dark:bg-amber-900/20 dark:border-amber-800 dark:text-amber-300"
      role="alert"
    >
      <AlertTriangle class="h-5 w-5 shrink-0 mt-0.5" aria-hidden="true" />
      <div class="flex-1">
        <p v-for="detector in session.notReadyDetectors" :key="detector.name">
          Detektor '{{ detector.name }}' ist aktiviert, aber nicht konfiguriert
        </p>
      </div>
    </div>

    <header class="border-b border-default">
      <div class="mx-auto flex items-center gap-3 px-4 py-4" :class="containerClass">
        <h1 class="text-xl font-semibold text-content">Medizinischer Dokumenten-Anonymisierer</h1>
        <button
          type="button"
          class="ml-auto p-2 rounded-card text-content-subtle hover:text-content hover:bg-surface-muted transition-colors"
          :aria-label="isDark ? 'Zum hellen Design wechseln' : 'Zum dunklen Design wechseln'"
          @click="toggleDarkMode"
        >
          <Sun v-if="isDark" class="h-5 w-5" aria-hidden="true" />
          <Moon v-else class="h-5 w-5" aria-hidden="true" />
        </button>
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
import { AlertTriangle, Moon, Sun, X } from '@lucide/vue'
import InputPanel from '@/components/anonymizer/InputPanel.vue'
import ResultView from '@/components/anonymizer/ResultView.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()

const externalEndpointsLabel = computed(() =>
  session.externalEndpoints.map((endpoint) => `${endpoint.name} (${endpoint.host})`).join(', '),
)

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
