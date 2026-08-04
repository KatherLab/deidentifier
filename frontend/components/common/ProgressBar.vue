<template>
  <!--
    Determinate progress bar (track + primary fill) in the app's visual
    language. `thin` renders the slim variant for compact rows/strips. The
    caller controls the width (e.g. w-full or a fixed w-20) via `class`.
  -->
  <div
    class="overflow-hidden rounded-full bg-surface-sunken"
    :class="thin ? 'h-1' : 'h-2.5'"
    role="progressbar"
    :aria-label="label"
    :aria-valuemin="0"
    :aria-valuemax="100"
    :aria-valuenow="roundedPercent"
    :aria-valuetext="valueText ?? `${roundedPercent} %`"
  >
    <div
      class="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
      :style="{ width: `${clampedPercent}%` }"
    ></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  /** Progress in percent (clamped to 0–100). */
  percent: number
  /** Accessible name of the bar. */
  label: string
  /** Slim variant (h-1) for compact rows/strips instead of h-2.5. */
  thin?: boolean
  /** Optional aria-valuetext (defaults to the rounded percent). */
  valueText?: string
}

const props = withDefaults(defineProps<Props>(), { thin: false, valueText: undefined })

const clampedPercent = computed(() => Math.min(Math.max(props.percent, 0), 100))
const roundedPercent = computed(() => Math.round(clampedPercent.value))
</script>
