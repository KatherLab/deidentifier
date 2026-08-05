<template>
  <div
    class="border-b px-4 py-2 text-center text-sm font-medium"
    :class="colorClass"
    role="region"
    :aria-label="t('banner.label')"
    data-testid="deployment-banner"
  >
    <div class="mx-auto flex max-w-[96rem] items-center justify-center gap-2">
      <Megaphone class="h-4 w-4 shrink-0" aria-hidden="true" />
      <!-- Operator-authored text from BANNER_TEXT: shown verbatim, never
           translated. -->
      <span>{{ text }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Megaphone } from '@lucide/vue'
import type { BannerColor } from '@/types/anonymizer'

interface Props {
  text: string
  color?: BannerColor
}

const props = withDefaults(defineProps<Props>(), {
  color: 'amber',
})

const { t } = useI18n()

/** Full class strings — Tailwind cannot see dynamically composed names. */
const COLOR_CLASSES: Record<BannerColor, string> = {
  amber:
    'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-200',
  red: 'border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-900/30 dark:text-red-200',
  blue: 'border-blue-300 bg-blue-50 text-blue-900 dark:border-blue-800 dark:bg-blue-900/30 dark:text-blue-200',
  green:
    'border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-900/30 dark:text-green-200',
  gray: 'border-slate-300 bg-slate-100 text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200',
}

const colorClass = computed(() => COLOR_CLASSES[props.color] ?? COLOR_CLASSES.amber)
</script>
