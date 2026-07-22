<template>
  <span
    :class="[
      'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold',
      getPillClass(color),
      $attrs.class,
    ]"
  >
    <slot>{{ label }}</slot>
  </span>
</template>

<script setup lang="ts">
import { getPillClass } from '@/utils/statusStyles'

defineOptions({ inheritAttrs: false })

interface Props {
  label?: string
  // Generic color pill map (dark-mode aware). Values:
  // blue|green|yellow|amber|red|pink|purple|teal|cyan|orange|gray
  color?: string
}

withDefaults(defineProps<Props>(), {
  label: '',
  color: 'gray',
})
</script>
