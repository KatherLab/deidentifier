<template>
  <!--
    Batch progress card (loading phase, >1 documents): overall bar over ALL
    concurrently processing documents plus one compact status row per
    document. Single-document runs keep the existing ProcessingCard.
  -->
  <div
    class="w-full max-w-xl space-y-4 rounded-modal border border-default bg-surface p-8 shadow-sm"
  >
    <p class="text-center text-sm font-medium text-content">
      {{ t('batch.parallel', { count: session.documents.length }) }}
    </p>

    <ProgressBar
      class="w-full"
      :percent="session.batchOverallPercent"
      :label="t('batch.overall_label')"
    />

    <p class="text-center text-sm text-content-muted" aria-live="polite">
      <span class="font-semibold text-content">{{
        formatPercent(session.batchOverallPercent)
      }}</span>
      · {{ settledSummary }}
    </p>

    <ul class="max-h-[50vh] space-y-1.5 overflow-y-auto">
      <li
        v-for="doc in session.documents"
        :key="doc.id"
        class="flex items-center gap-2.5 rounded-card bg-surface-muted px-3 py-2"
      >
        <!-- Status icon (always paired with the accessible status label). -->
        <Clock
          v-if="doc.status === 'queued'"
          class="h-4 w-4 shrink-0 text-content-subtle"
          aria-hidden="true"
        />
        <LoadingSpinner
          v-else-if="doc.status === 'processing'"
          size="small"
          color="gray"
          inline
          label=""
          class="shrink-0"
        />
        <Check
          v-else-if="doc.status === 'done'"
          class="h-4 w-4 shrink-0 text-green-600 dark:text-green-400"
          aria-hidden="true"
        />
        <X v-else class="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />

        <span class="min-w-0 flex-1 truncate text-left text-sm text-content" :title="doc.name">
          {{ doc.name }}
        </span>

        <ProgressBar
          thin
          class="w-20 shrink-0"
          :percent="documentBatchPercent(doc)"
          :label="t('batch.row_progress', { name: doc.name })"
        />

        <span
          class="shrink-0 text-right text-xs tabular-nums"
          :class="doc.status === 'error' ? 'text-red-600 dark:text-red-400' : 'text-content-subtle'"
        >
          {{ statusLabel(doc) }}
        </span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Clock, X } from '@lucide/vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import { documentBatchPercent, useSessionStore } from '@/stores/session'
import { formatPercent } from '@/utils/format'
import type { SessionDocument } from '@/stores/session'

const { t } = useI18n()
const session = useSessionStore()

/** "X von N abgeschlossen" (done + error), plus failures only when any. */
const settledSummary = computed(() => {
  let summary = t('batch.settled', {
    done: session.batchSettledCount,
    total: session.documents.length,
  })
  if (session.batchFailedCount > 0) {
    summary += ` · ${t('batch.failed', { count: session.batchFailedCount })}`
  }
  return summary
})

/** Compact right-aligned status label of one document row. */
function statusLabel(doc: SessionDocument): string {
  switch (doc.status) {
    case 'queued':
      return t('batch.status.queued')
    case 'done':
      return t('batch.status.done')
    case 'error':
      return t('batch.status.error')
    default: {
      const progress = doc.progress
      if (progress === null) return formatPercent(doc.progressMaxPercent)
      const counts = { done: progress.done, total: progress.total }
      switch (progress.stage) {
        case 'ocr':
          return t('batch.status.ocr', counts)
        case 'detection':
          return t('batch.status.detection', counts)
        default:
          return t('batch.status.recheck')
      }
    }
  }
}
</script>
