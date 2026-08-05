<template>
  <div ref="container" class="relative">
    <button
      type="button"
      class="rounded-card p-2 text-content-subtle transition-colors hover:bg-surface-muted hover:text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :aria-label="t('language.select')"
      :aria-expanded="open"
      aria-haspopup="true"
      @click="toggle()"
    >
      <Languages class="h-5 w-5" aria-hidden="true" />
    </button>
    <div
      v-if="open"
      class="absolute right-0 top-full z-20 mt-2 w-44 rounded-card border border-default bg-surface p-1 shadow-lg"
      role="menu"
      :aria-label="t('language.select')"
    >
      <button
        v-for="loc in supportedLocales"
        :key="loc"
        type="button"
        role="menuitemradio"
        :aria-checked="loc === locale"
        class="flex w-full items-center justify-between gap-2 rounded-card px-3 py-2 text-left text-sm text-content transition-colors hover:bg-surface-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :class="loc === locale ? 'font-medium' : ''"
        @click="select(loc)"
      >
        {{ t(`language.${loc}`) }}
        <Check v-if="loc === locale" class="h-4 w-4 text-primary" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Languages } from '@lucide/vue'
import { usePopover } from '@/composables/usePopover'
import { useLocale } from '@/composables/useLocale'
import type { SupportedLocale } from '@/i18n'

const { t } = useI18n()
const { locale, supportedLocales, setLocale } = useLocale()

const container = ref<HTMLElement | null>(null)
const { open, toggle, close } = usePopover(container)

async function select(loc: SupportedLocale): Promise<void> {
  await setLocale(loc)
  close()
}
</script>
