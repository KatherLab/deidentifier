<template>
  <!--
    Progress card of ONE document: determinate bar once stream events arrive,
    shimmer before, queue notice while the document waits for a free stream
    slot. Used on the landing page (while no document finished yet) and in the
    result view when the ACTIVE document is still queued/processing.
  -->
  <div
    class="w-full max-w-lg space-y-4 rounded-modal border border-default bg-surface p-8 text-center shadow-sm"
  >
    <Clock
      v-if="document.status === 'queued'"
      class="mx-auto h-10 w-10 text-content-subtle"
      aria-hidden="true"
    />
    <FileText v-else class="mx-auto h-10 w-10 text-content-subtle" aria-hidden="true" />
    <p class="text-sm font-medium text-content break-all">{{ document.name }}</p>

    <template v-if="document.status === 'queued'">
      <p class="text-sm text-content-muted" aria-live="polite">{{ t('processing.queued') }}</p>
    </template>
    <template v-else>
      <div
        class="h-2.5 w-full overflow-hidden rounded-full bg-surface-sunken"
        role="progressbar"
        :aria-label="t('processing.progress_label')"
        :aria-valuemin="0"
        :aria-valuemax="100"
        :aria-valuenow="roundedPercent ?? undefined"
        :aria-valuetext="stageLabel"
      >
        <div
          v-if="percent !== null"
          class="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
          :style="{ width: `${percent}%` }"
        ></div>
        <div v-else class="progress-shimmer h-full w-1/3 rounded-full bg-primary"></div>
      </div>

      <p class="text-sm text-content-muted" aria-live="polite">
        <span v-if="percent !== null" class="font-semibold text-content">{{
          formatPercent(percent)
        }}</span>
        {{ stageLabel }}
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Clock, FileText } from '@lucide/vue'
import { documentProgressPercent } from '@/stores/session'
import { formatPercent } from '@/utils/format'
import type { SessionDocument } from '@/stores/session'

interface Props {
  document: SessionDocument
}

const props = defineProps<Props>()

const { t } = useI18n()

/** Streamed overall percent (null → indeterminate shimmer). */
const percent = computed(() => documentProgressPercent(props.document))
const roundedPercent = computed(() => (percent.value === null ? null : Math.round(percent.value)))

/** Label for the current pipeline stage. */
const stageLabel = computed(() => {
  const progress = props.document.progress
  if (progress === null) return t('processing.stage.default')
  const counts = { done: progress.done, total: progress.total }
  switch (progress.stage) {
    case 'ocr':
      return t('processing.stage.ocr', counts)
    case 'detection':
      return t('processing.stage.detection', counts)
    case 'recheck':
      return t('processing.stage.recheck')
    default:
      return t('processing.stage.default')
  }
})
</script>

<style scoped>
/* Indeterminate shimmer: a third-width bar sweeping across the track until
   the first streamed progress event arrives. */
@keyframes progress-shimmer {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(300%);
  }
}
.progress-shimmer {
  animation: progress-shimmer 1.4s ease-in-out infinite;
}
</style>
