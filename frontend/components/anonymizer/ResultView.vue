<template>
  <section class="space-y-5">
    <!-- Document switcher (batch runs only). -->
    <template v-if="session.documents.length > 1">
      <DocumentBar />
      <!-- Slim strip while documents still process in the background;
           disappears once every document is settled (done or error). -->
      <div v-if="session.batchSettledCount < session.documents.length" class="space-y-1.5">
        <ProgressBar
          thin
          class="w-full"
          :percent="session.batchOverallPercent"
          label="Gesamtfortschritt der Verarbeitung im Hintergrund"
        />
        <p class="text-xs text-content-subtle" aria-live="polite">
          Verarbeitung im Hintergrund: {{ session.batchSettledCount }} von
          {{ session.documents.length }} abgeschlossen
        </p>
      </div>
    </template>

    <!-- Active document DONE: full result header + panels. -->
    <template v-if="doc && doc.status === 'done' && result">
      <!-- Header: validation status, meta and actions in one row. -->
      <div class="flex flex-wrap items-center gap-3">
        <StatusBadge
          :label="validationStatusLabel(result.validation.status)"
          :color="validationStatusColor(result.validation.status)"
          class="text-sm"
        />
        <StatusBadge :label="sourceTypeLabel(result.source_type)" color="gray" />
        <span class="text-xs text-content-subtle">
          Verarbeitet in {{ Math.round(result.timing_ms.total) }} ms
        </span>
        <span v-if="batchSummary" class="text-xs text-content-subtle" aria-live="polite">
          {{ batchSummary }}
        </span>
        <span
          v-if="session.rerunning"
          class="inline-flex items-center gap-1.5 text-xs text-content-subtle"
          aria-live="polite"
        >
          <LoadingSpinner size="small" color="gray" inline label="" />
          Wird neu berechnet …
        </span>
        <!-- Copy/download always act on the anonymized text, regardless of the
             visible panels. -->
        <div class="ml-auto flex flex-wrap items-center gap-2">
          <BaseButton size="sm" variant="secondary" @click="copyAnonymized">
            <Copy class="h-4 w-4" aria-hidden="true" />
            Kopieren
          </BaseButton>
          <BaseButton size="sm" variant="secondary" @click="downloadAnonymized">
            <Download class="h-4 w-4" aria-hidden="true" />
            Als .txt
          </BaseButton>
          <BaseButton
            v-if="canExportPdf"
            size="sm"
            variant="secondary"
            :loading="exportingPdf"
            @click="downloadRedactedPdf"
          >
            <FileDown v-if="!exportingPdf" class="h-4 w-4" aria-hidden="true" />
            PDF herunterladen
          </BaseButton>
          <BaseButton size="sm" @click="session.reset()">{{ resetLabel }}</BaseButton>
        </div>
      </div>

      <!-- Panel selector: 1–3 views at once; enabling a 4th disables the oldest. -->
      <div class="flex flex-wrap items-center gap-3">
        <div
          class="inline-flex flex-wrap gap-1 rounded-card border border-default bg-surface-sunken p-1"
          role="group"
          aria-label="Ansichten wählen (bis zu drei gleichzeitig)"
        >
          <button
            v-for="panel in availablePanels"
            :key="panel.id"
            type="button"
            :aria-pressed="isActive(panel.id)"
            class="inline-flex items-center gap-1.5 rounded-card px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :class="
              isActive(panel.id)
                ? 'bg-surface text-content shadow-sm'
                : 'text-content-muted hover:text-content'
            "
            @click="session.togglePanel(panel.id)"
          >
            <Check v-if="isActive(panel.id)" class="h-3.5 w-3.5 text-primary" aria-hidden="true" />
            {{ panel.label }}
          </button>
        </div>
        <span class="text-xs text-content-subtle">Bis zu 3 Ansichten gleichzeitig</span>
      </div>

      <!-- Panels: equal-height cards in a responsive grid. Reading order
           follows the transformation: Original → Quellprüfung → Ergebnis. -->
      <div class="grid items-start gap-4" :class="gridClass">
        <!-- Original document: PDF sources render the untouched upload, text
             sources the extracted source text. -->
        <section v-if="isActive('original')" :class="panelCardClass">
          <header :class="panelHeaderClass">
            <h3 class="text-sm font-semibold text-content">Original</h3>
          </header>
          <template v-if="isPdfSource">
            <iframe
              v-if="session.originalPreviewUrl"
              :src="session.originalPreviewUrl"
              title="Originaldokument"
              class="min-h-0 w-full flex-1"
            ></iframe>
            <p v-else class="p-6 text-sm text-content-subtle">
              Die Originaldatei ist nicht mehr verfügbar.
            </p>
          </template>
          <!-- v-text: the panel is whitespace-pre-wrap, so template indentation
               must not leak in. -->
          <div
            v-else
            class="min-h-0 flex-1 overflow-y-auto p-6 font-mono text-sm leading-relaxed whitespace-pre-wrap break-words text-content"
            v-text="result.source_text"
          ></div>
        </section>

        <!-- Quellprüfung: interactive source review (primary view). -->
        <section v-if="isActive('source')" :class="panelCardClass">
          <header :class="panelHeaderClass">
            <h3 class="text-sm font-semibold text-content">Quellprüfung</h3>
          </header>
          <EntityHighlights
            class="min-h-0 flex-1"
            :source-text="result.source_text"
            :entities="result.entities"
            :warnings="result.validation.warnings"
            :selected-index="session.selectedEntityIndex"
            @select="session.selectEntity($event)"
          />
          <EntityDetailPanel
            v-if="session.selectedEntity"
            :entity="session.selectedEntity"
            @close="session.selectEntity(null)"
          />
          <p
            v-else
            class="shrink-0 border-t border-default px-4 py-2.5 text-xs text-content-subtle"
          >
            Klicken Sie auf eine markierte Stelle für Details – oder markieren Sie beliebigen Text,
            um ihn manuell zu schwärzen.
          </p>
        </section>

        <!-- Redacted-PDF preview (PDF sources only; refreshed after every
             override re-run, so it always mirrors the text result). -->
        <section v-if="isActive('pdf')" :class="panelCardClass">
          <header class="shrink-0 space-y-0.5 border-b border-default bg-surface-muted px-4 py-2.5">
            <h3 class="text-sm font-semibold text-content">Geschwärztes PDF</h3>
            <p v-if="result.source_type === 'pdf-ocr'" class="text-xs text-content-subtle">
              Rekonstruiertes Dokument – Layout angenähert, Originalpixel werden verworfen.
            </p>
          </header>
          <div
            v-if="session.pdfPreviewLoading"
            class="flex flex-1 items-center justify-center gap-2 p-4 text-sm text-content-subtle"
            aria-live="polite"
          >
            <LoadingSpinner size="small" color="gray" inline label="" />
            PDF wird erzeugt …
          </div>
          <div v-else-if="session.pdfPreviewError" class="space-y-3 p-4">
            <p class="rounded-card px-3 py-2 text-sm" :class="getBannerClass('red')">
              {{ session.pdfPreviewError }}
            </p>
            <BaseButton size="sm" variant="secondary" @click="session.refreshPdfPreview()">
              Erneut versuchen
            </BaseButton>
          </div>
          <iframe
            v-else-if="session.pdfPreviewUrl"
            :src="session.pdfPreviewUrl"
            title="Geschwärztes PDF (Vorschau)"
            class="min-h-0 w-full flex-1"
          ></iframe>
          <p v-else class="p-6 text-sm text-content-subtle">Keine Vorschau verfügbar.</p>
        </section>

        <!-- Anonymized output as plain selectable text. -->
        <section v-if="isActive('anonymized')" :class="panelCardClass">
          <header :class="panelHeaderClass">
            <h3 class="text-sm font-semibold text-content">Anonymisierter Text</h3>
          </header>
          <div
            class="min-h-0 flex-1 overflow-y-auto p-6 font-sans text-[15px] leading-relaxed whitespace-pre-wrap break-words text-content"
            v-text="result.anonymized_text"
          ></div>
        </section>
      </div>

      <!-- Entity counts by type -->
      <section
        v-if="session.entityCounts.length > 0"
        class="flex flex-wrap items-center gap-2"
        aria-label="Erkannte Entitäten"
      >
        <h3 class="text-sm font-semibold text-content">Erkannte Entitäten:</h3>
        <StatusBadge
          v-for="item in session.entityCounts"
          :key="item.type"
          :label="`${entityTypeLabel(item.type)}: ${item.count}`"
          color="blue"
        />
      </section>
      <p v-else class="text-sm text-content-subtle">Keine Entitäten erkannt.</p>

      <!-- Warnings -->
      <WarningsList
        :validation-warnings="result.validation.warnings"
        :general-warnings="result.warnings"
        @locate="showWarningInSource"
      />
    </template>

    <!-- Active document FAILED: error card with per-document retry. -->
    <template v-else-if="doc && doc.status === 'error'">
      <div class="flex flex-wrap items-center gap-3">
        <span v-if="batchSummary" class="text-xs text-content-subtle" aria-live="polite">
          {{ batchSummary }}
        </span>
        <div class="ml-auto">
          <BaseButton size="sm" @click="session.reset()">{{ resetLabel }}</BaseButton>
        </div>
      </div>
      <div class="flex justify-center py-10">
        <div
          class="w-full max-w-lg space-y-4 rounded-modal border border-default bg-surface p-8 text-center shadow-sm"
        >
          <FileX class="mx-auto h-10 w-10 text-red-600 dark:text-red-400" aria-hidden="true" />
          <p class="text-sm font-medium text-content break-all">{{ doc.name }}</p>
          <p class="rounded-card px-3 py-2 text-sm" :class="getBannerClass('red')" role="alert">
            {{ doc.error ?? 'Anonymisierung fehlgeschlagen.' }}
          </p>
          <BaseButton variant="secondary" @click="session.retryDocument(doc.id)">
            Erneut versuchen
          </BaseButton>
        </div>
      </div>
    </template>

    <!-- Active document still QUEUED/PROCESSING: progress card in place of
         the panels (switching to a finished document stays possible above). -->
    <template v-else-if="doc">
      <div class="flex flex-wrap items-center gap-3">
        <span v-if="batchSummary" class="text-xs text-content-subtle" aria-live="polite">
          {{ batchSummary }}
        </span>
        <div class="ml-auto">
          <BaseButton size="sm" @click="session.reset()">{{ resetLabel }}</BaseButton>
        </div>
      </div>
      <div class="flex justify-center py-10">
        <ProcessingCard :document="doc" />
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Copy, Download, FileDown, FileX } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import DocumentBar from '@/components/anonymizer/DocumentBar.vue'
import EntityHighlights from '@/components/anonymizer/EntityHighlights.vue'
import EntityDetailPanel from '@/components/anonymizer/EntityDetailPanel.vue'
import ProcessingCard from '@/components/anonymizer/ProcessingCard.vue'
import WarningsList from '@/components/anonymizer/WarningsList.vue'
import { useSessionStore } from '@/stores/session'
import type { ResultPanelId } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { useFileDownload } from '@/composables/useFileDownload'
import { anonymizeApi } from '@/services/anonymizeApi'
import { extractPdfExportErrorMessage } from '@/utils/errors'
import { getBannerClass } from '@/utils/statusStyles'
import {
  entityTypeLabel,
  sourceTypeLabel,
  validationStatusColor,
  validationStatusLabel,
} from '@/utils/entityLabels'

const session = useSessionStore()
const toast = useToast()
const { downloadBlob, downloadFromApi } = useFileDownload()

/** The ACTIVE document of the batch — everything below renders its state. */
const doc = computed(() => session.activeDocument)
const result = computed(() => session.result)

/** Shared card chrome so all panel columns align at the same height. */
const panelCardClass =
  'flex h-[72vh] min-w-0 flex-col overflow-hidden rounded-card border border-default bg-surface'
const panelHeaderClass =
  'flex shrink-0 items-baseline gap-2 border-b border-default bg-surface-muted px-4 py-2.5'

const isPdfSource = computed(
  () => result.value?.source_type === 'pdf' || result.value?.source_type === 'pdf-ocr',
)

const availablePanels = computed<{ id: ResultPanelId; label: string }[]>(() => {
  // Chip order mirrors the panel reading order: Original → Quellprüfung → Ergebnis.
  const panels: { id: ResultPanelId; label: string }[] = [
    { id: 'original', label: 'Original' },
    { id: 'source', label: 'Quellprüfung' },
  ]
  if (isPdfSource.value) panels.push({ id: 'pdf', label: 'Geschwärztes PDF' })
  panels.push({ id: 'anonymized', label: 'Anonymisierter Text' })
  return panels
})

/**
 * The active panels live ON the document entry (store), so switching
 * documents restores each document's own panel selection.
 */
function isActive(id: ResultPanelId): boolean {
  return session.activePanels.includes(id)
}

const gridClass = computed(() => {
  switch (session.activePanels.length) {
    case 1:
      return 'grid-cols-1'
    case 2:
      return 'grid-cols-1 lg:grid-cols-2'
    default:
      // Three columns only on very wide screens; two columns wrapping at lg.
      return 'grid-cols-1 lg:grid-cols-2 xl:grid-cols-3'
  }
})

/** "3 von 5 Dokumenten verarbeitet · 1 mit Prüfbedarf" (batch runs only). */
const batchSummary = computed<string | null>(() => {
  const docs = session.documents
  if (docs.length <= 1) return null
  const done = docs.filter((entry) => entry.status === 'done').length
  const failed = docs.filter((entry) => entry.status === 'error').length
  const review = docs.filter(
    (entry) => entry.status === 'done' && entry.result?.validation.status !== 'PASS',
  ).length
  let summary = `${done} von ${docs.length} Dokumenten verarbeitet`
  if (review > 0) summary += ` · ${review} mit Prüfbedarf`
  if (failed > 0) summary += ` · ${failed} fehlgeschlagen`
  return summary
})

const resetLabel = computed(() =>
  session.documents.length > 1 ? 'Neue Dokumente' : 'Neues Dokument',
)

async function copyAnonymized() {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(result.value.anonymized_text)
    toast.success('Anonymisierter Text in die Zwischenablage kopiert.')
  } catch {
    toast.error('Kopieren fehlgeschlagen. Bitte markieren und manuell kopieren.')
  }
}

function downloadAnonymized() {
  if (!result.value) return
  downloadBlob(result.value.anonymized_text, 'anonymisiert.txt', 'text/plain;charset=utf-8')
}

/**
 * Redacted-PDF export is only possible for PDF sources AND while the original
 * File is still held in memory (it is re-sent — the server stores nothing).
 */
const canExportPdf = computed(() => isPdfSource.value && session.sourceFile !== null)

const exportingPdf = ref(false)

/**
 * Download the redacted PDF of the ACTIVE document with all of ITS current
 * overrides, request_id and batch policy/rules applied. The preview blob (if
 * loaded) already reflects the current overrides, so it is reused directly
 * instead of re-requesting the export. The fallback request can take up to a
 * minute for scans on a backend cache miss, hence the loading state.
 */
async function downloadRedactedPdf() {
  const entry = doc.value
  const file = entry?.file
  const requestId = entry?.result?.request_id
  if (!entry || !file || requestId === undefined || exportingPdf.value) return
  if (entry.pdfPreviewBlob !== null && !entry.pdfPreviewLoading) {
    downloadBlob(entry.pdfPreviewBlob, 'anonymisiert.pdf')
    return
  }
  const overrides = [...entry.overrides.values()]
  exportingPdf.value = true
  try {
    await downloadFromApi(
      () => anonymizeApi.exportPdf(file, requestId, overrides, entry.policy, entry.rules),
      'anonymisiert.pdf',
    )
  } catch (err) {
    toast.error(await extractPdfExportErrorMessage(err))
  } finally {
    exportingPdf.value = false
  }
}

/** "Im Text anzeigen" from the warnings list: make sure the review is visible. */
function showWarningInSource() {
  session.activatePanel('source')
}
</script>
