<template>
  <div class="min-h-screen">
    <!-- Deployment banner (BANNER_* in the backend .env), above everything. -->
    <DeploymentBanner
      v-if="session.banner"
      :text="session.banner.text"
      :color="session.banner.color"
    />

    <header class="border-b border-default">
      <div class="mx-auto flex items-center gap-3 px-4 py-4" :class="containerClass">
        <h1 class="text-xl font-semibold text-content">{{ t('app.title') }}</h1>

        <div class="ml-auto flex items-center gap-1.5">
          <!-- How long the server keeps the current result — and the way to
               top it up BEFORE it runs low, so stepping away from the desk
               does not cost a re-run. Always reachable while a result is on
               screen; the last-minute warning lives in the result view. -->
          <button
            v-if="lifetime.remaining.value !== null"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default"
            :class="lifetimeChipClass"
            :disabled="!session.resultsCanExtend || session.extendingResults"
            :aria-label="lifetimeLabel"
            :title="lifetimeLabel"
            @click="session.extendResults()"
          >
            <Timer class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span v-if="lifetime.isExpired.value">{{ t('result.lifetime.expired') }}</span>
            <span v-else>{{
              t('result.lifetime.remaining', { time: lifetime.formatted.value })
            }}</span>
            <Plus
              v-if="session.resultsCanExtend && !lifetime.isExpired.value"
              class="h-3.5 w-3.5 shrink-0"
              aria-hidden="true"
            />
          </button>

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

          <!-- Who is signed in, when this deployment has a sign-in gate. -->
          <div v-if="auth.enabled && auth.authenticated" ref="accountContainer" class="relative">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded-full border border-default px-2.5 py-1 text-xs font-medium text-content-subtle transition-colors hover:bg-surface-muted hover:text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              :aria-label="t('auth.user.label', { name: accountName })"
              :aria-expanded="accountOpen"
              @click="toggleAccount()"
            >
              <User class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span class="max-w-[10rem] truncate">{{ accountName }}</span>
            </button>
            <div
              v-if="accountOpen"
              class="absolute right-0 top-full z-20 mt-2 w-64 rounded-card border border-default bg-surface p-4 shadow-lg"
              role="dialog"
              :aria-label="t('auth.user.menu_label')"
            >
              <p class="truncate text-sm font-medium text-content">{{ accountName }}</p>
              <p v-if="auth.user?.email" class="truncate text-xs text-content-subtle">
                {{ auth.user.email }}
              </p>
              <BaseButton
                class="mt-3 w-full"
                variant="secondary"
                size="sm"
                :loading="auth.signingOut"
                @click="auth.signOut()"
              >
                <LogOut class="h-4 w-4" aria-hidden="true" />
                {{ t('auth.user.sign_out') }}
              </BaseButton>
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
      <!-- Nothing renders before the sign-in gate has answered: flashing the
           input panel at someone who is about to be sent to the identity
           provider looks like the app lost their work. -->
      <div v-if="!auth.ready" class="flex justify-center py-16">
        <LoadingSpinner :label="t('auth.gate.checking')" />
      </div>
      <SignInGate v-else-if="auth.blocked" />
      <ResultView v-else-if="session.phase === 'result'" />
      <InputPanel v-else />
    </main>

    <!-- The version an operator is actually running — the first thing any bug
         report needs, and otherwise only readable from /api/v1/status. -->
    <footer
      v-if="session.status"
      class="mx-auto px-4 pb-6 text-center text-xs text-content-subtle"
      :class="containerClass"
    >
      {{ t('app.version', { version: session.status.version }) }}
    </footer>

    <ToastContainer />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, LogOut, Moon, Plus, Settings, Sun, Timer, User } from '@lucide/vue'
import InputPanel from '@/components/anonymizer/InputPanel.vue'
import ResultView from '@/components/anonymizer/ResultView.vue'
import SignInGate from '@/components/auth/SignInGate.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import DeploymentBanner from '@/components/common/DeploymentBanner.vue'
import LanguageSwitcher from '@/components/common/LanguageSwitcher.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'
import { usePopover } from '@/composables/usePopover'
import { useResultLifetime } from '@/composables/useResultLifetime'
import { useAuthStore } from '@/stores/auth'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'

const { t } = useI18n()
const auth = useAuthStore()
const session = useSessionStore()
const settings = useSettingsStore()

/** Providers are not required to send a name; the email is the fallback, and
 *  a generic word the fallback for that. */
const accountName = computed(() => auth.user?.name || auth.user?.email || t('auth.user.signed_in'))

// ---------------------------------------------------------------------------
// Result lifetime chip: the batch-wide countdown, extendable at any time
// ---------------------------------------------------------------------------

const lifetime = useResultLifetime(() => session.resultsExpireAt)

/** Quiet while there is time, amber once the result is nearly gone. */
const lifetimeChipClass = computed(() => {
  if (lifetime.isExpiring.value || lifetime.isExpired.value) {
    return 'border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300 dark:hover:bg-amber-900/40'
  }
  return 'border-default text-content-subtle hover:bg-surface-muted hover:text-content'
})

/**
 * The chip shows only the time; the accessible name carries what it is and
 * what pressing it does — including why it does nothing at the ceiling.
 */
const lifetimeLabel = computed(() => {
  const time = lifetime.formatted.value
  if (lifetime.isExpired.value) return t('result.lifetime.expired_hint')
  if (!session.resultsCanExtend) return t('result.lifetime.extended_at_maximum', { time })
  return t('result.lifetime.extend_hint', { time })
})

const hintsContainer = ref<HTMLElement | null>(null)
const { open: hintsOpen, toggle: toggleHints } = usePopover(hintsContainer)

const settingsContainer = ref<HTMLElement | null>(null)
const { open: settingsOpen, toggle: toggleSettings } = usePopover(settingsContainer)

const accountContainer = ref<HTMLElement | null>(null)
const { open: accountOpen, toggle: toggleAccount } = usePopover(accountContainer)

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

onMounted(async () => {
  // The gate answers first: behind it, every other API call is a 401.
  await auth.initialize()
  if (!auth.blocked) void session.fetchStatus()
  // Closing the tab should end the server-side copy too, not leave it to the
  // cache TTL. `pagehide` fires where `beforeunload` is unreliable (mobile,
  // bfcache); the handler lives for the life of the app, so it is never
  // removed.
  window.addEventListener('pagehide', () => session.forgetResultsOnUnload())
})
</script>
