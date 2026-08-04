<template>
  <!--
    Horizontal document switcher (batch runs only): one chip per document with
    a status indicator. Clicking switches the active document — also while
    other documents are still processing.
  -->
  <nav
    class="flex flex-wrap gap-1.5 rounded-card border border-default bg-surface-sunken p-1.5"
    aria-label="Dokumente des Stapels"
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
        {{ processingPercent(doc) }} %
      </span>
      <span class="sr-only">{{ statusText(doc) }}</span>
    </button>
  </nav>
</template>

<script setup lang="ts">
import { Clock, X } from '@lucide/vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { documentProgressPercent, useSessionStore } from '@/stores/session'
import type { SessionDocument } from '@/stores/session'
import { validationStatusLabel } from '@/utils/entityLabels'

const session = useSessionStore()

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

/** Screen-reader status text (the icons/dots alone are never the only cue). */
function statusText(doc: SessionDocument): string {
  switch (doc.status) {
    case 'queued':
      return 'In der Warteschlange'
    case 'processing':
      return 'Wird verarbeitet'
    case 'error':
      return `Fehlgeschlagen: ${doc.error ?? 'Unbekannter Fehler'}`
    default:
      return doc.result ? validationStatusLabel(doc.result.validation.status) : 'Abgeschlossen'
  }
}
</script>
