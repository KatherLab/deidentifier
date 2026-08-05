<template>
  <!--
    Document switcher (batch runs only). Small batches get one chip per
    document; larger ones a compact prev/next + dropdown control that scales
    to hundreds of documents. Switching is possible while other documents are
    still processing.
  -->
  <nav
    v-if="session.documents.length <= COMPACT_THRESHOLD"
    class="flex flex-wrap gap-1.5 rounded-card border border-default bg-surface-sunken p-1.5"
    :aria-label="t('documents.nav_label')"
  >
    <button
      v-for="doc in session.documents"
      :key="doc.id"
      type="button"
      :title="doc.name"
      :aria-current="doc.id === session.activeDocumentId ? 'true' : undefined"
      class="inline-flex max-w-56 items-center gap-1.5 rounded-card border px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :class="
        doc.id === session.activeDocumentId
          ? 'border-primary bg-surface text-content shadow-sm'
          : 'border-transparent text-content-muted hover:bg-surface hover:text-content'
      "
      @click="session.selectDocument(doc.id)"
    >
      <!-- Status indicator (always paired with the accessible status text). -->
      <Clock
        v-if="doc.status === 'queued'"
        class="h-3.5 w-3.5 shrink-0 text-content-subtle"
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
      <X
        v-else-if="doc.status === 'error'"
        class="h-3.5 w-3.5 shrink-0 text-red-600 dark:text-red-400"
        aria-hidden="true"
      />
      <span
        v-else
        class="h-2 w-2 shrink-0 rounded-full"
        :class="doneDotClass(doc)"
        aria-hidden="true"
      ></span>

      <span class="min-w-0 truncate">{{ doc.name }}</span>

      <span
        v-if="doc.status === 'processing' && processingPercent(doc) !== null"
        class="shrink-0 text-xs tabular-nums text-content-subtle"
      >
        {{ formatPercent(doc.progressMaxPercent) }}
      </span>
      <span class="sr-only">{{ statusText(doc) }}</span>
    </button>
  </nav>

  <nav v-else class="flex items-center gap-2" :aria-label="t('documents.nav_label')">
    <BaseButton
      variant="icon"
      tone="gray"
      :disabled="activeIndex <= 0"
      :aria-label="t('documents.previous')"
      @click="step(-1)"
    >
      <ChevronLeft class="h-4 w-4" aria-hidden="true" />
    </BaseButton>
    <label for="document-select" class="sr-only">{{ t('documents.select') }}</label>
    <select
      id="document-select"
      :value="session.activeDocumentId"
      class="min-w-0 max-w-lg flex-1 rounded-card border border-strong bg-surface px-2 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      @change="onSelect"
    >
      <option v-for="doc in session.documents" :key="doc.id" :value="doc.id">
        {{ statusGlyph(doc) }} {{ doc.name }}
      </option>
    </select>
    <BaseButton
      variant="icon"
      tone="gray"
      :disabled="activeIndex >= session.documents.length - 1"
      :aria-label="t('documents.next')"
      @click="step(1)"
    >
      <ChevronRight class="h-4 w-4" aria-hidden="true" />
    </BaseButton>
    <span class="shrink-0 text-xs tabular-nums text-content-subtle" aria-live="polite">
      {{ activeIndex + 1 }} / {{ session.documents.length }}
    </span>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronLeft, ChevronRight, Clock, X } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { documentProgressPercent, useSessionStore } from '@/stores/session'
import type { SessionDocument } from '@/stores/session'
import { validationStatusLabel } from '@/utils/entityLabels'
import { formatPercent } from '@/utils/format'

/** Above this batch size, chips would wall up — switch to the dropdown. */
const COMPACT_THRESHOLD = 10

const { t } = useI18n()
const session = useSessionStore()

const activeIndex = computed(() =>
  session.documents.findIndex((doc) => doc.id === session.activeDocumentId),
)

function step(direction: -1 | 1): void {
  const target = session.documents[activeIndex.value + direction]
  if (target) session.selectDocument(target.id)
}

function onSelect(event: Event): void {
  session.selectDocument((event.target as HTMLSelectElement).value)
}

/** Rounded stream percent for a processing chip (null → spinner only). */
function processingPercent(doc: SessionDocument): number | null {
  const percent = documentProgressPercent(doc)
  return percent === null ? null : Math.round(percent)
}

/** Dot color of a finished document, by its validation status. */
function doneDotClass(doc: SessionDocument): string {
  switch (doc.result?.validation.status) {
    case 'PASS':
      return 'bg-green-500 dark:bg-green-400'
    case 'REVIEW_REQUIRED':
      return 'bg-amber-500 dark:bg-amber-400'
    default:
      return 'bg-red-500 dark:bg-red-400'
  }
}

/** Compact status prefix for dropdown options (plain text — no icons there). */
function statusGlyph(doc: SessionDocument): string {
  switch (doc.status) {
    case 'queued':
      return '·'
    case 'processing': {
      const percent = processingPercent(doc)
      return percent === null ? '…' : formatPercent(percent)
    }
    case 'error':
      return '✗'
    default:
      switch (doc.result?.validation.status) {
        case 'PASS':
          return '✓'
        case 'REVIEW_REQUIRED':
          return '⚠'
        default:
          return '✗'
      }
  }
}

/** Screen-reader status text (the icons/dots alone are never the only cue). */
function statusText(doc: SessionDocument): string {
  switch (doc.status) {
    case 'queued':
      return t('documents.status.queued')
    case 'processing':
      return t('documents.status.processing')
    case 'error':
      return t('documents.status.error', {
        message: doc.error ?? t('documents.status.unknown_error'),
      })
    default:
      return doc.result
        ? validationStatusLabel(doc.result.validation.status)
        : t('documents.status.done')
  }
}
</script>
