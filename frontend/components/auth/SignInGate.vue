<template>
  <div class="mx-auto max-w-md rounded-card border border-default bg-surface p-8 text-center">
    <div
      class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary-soft"
      aria-hidden="true"
    >
      <ShieldCheck class="h-6 w-6 text-primary" />
    </div>

    <h2 class="mt-4 text-lg font-semibold text-content">{{ t('auth.gate.title') }}</h2>
    <p class="mt-2 text-sm text-content-subtle">{{ t('auth.gate.description') }}</p>

    <!-- Why the last attempt (or the last session) ended. Not a color-only
         signal: the icon is decorative, the sentence carries the meaning. -->
    <p
      v-if="problemMessage"
      role="status"
      class="mt-4 flex items-start gap-2 rounded-card border border-amber-300 bg-amber-50 p-3 text-left text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200"
    >
      <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{{ problemMessage }}</span>
    </p>

    <BaseButton class="mt-6 w-full" size="lg" @click="auth.signIn()">
      <LogIn class="h-4 w-4" aria-hidden="true" />
      {{ t('auth.gate.sign_in') }}
    </BaseButton>

    <p class="mt-4 text-xs text-content-subtle">{{ t('auth.gate.note') }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, LogIn, ShieldCheck } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import { useAuthStore } from '@/stores/auth'

const { t, te } = useI18n()
const auth = useAuthStore()

/** An unknown code from a newer backend falls back to the generic sentence
 *  rather than rendering a raw key. */
const problemMessage = computed(() => {
  const problem = auth.problem
  if (!problem) return ''
  const key = `auth.errors.${problem}`
  return te(key) ? t(key) : t('auth.errors.unknown')
})
</script>
