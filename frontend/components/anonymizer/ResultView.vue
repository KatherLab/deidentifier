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
      <!-- Header: ONE status statement left, ONE export action right. -->
      <div class="flex flex-wrap items-center gap-3">
        <component
          :is="statusIcon"
          class="h-5 w-5 shrink-0"
          :class="statusIconClass"
          aria-hidden="true"
        />
        <p class="text-base font-medium text-content">{{ statusHeadline }}</p>
        <span
          v-if="session.rerunning"
          class="inline-flex items-center gap-1.5 text-xs text-content-subtle"
          aria-live="polite"
        >
          <LoadingSpinner size="small" color="gray" inline label="" />
          Wird neu berechnet …
        </span>
        <!-- Export always acts on the anonymized result, regardless of the
             visible panels. -->
        <div class="ml-auto flex flex-wrap items-center gap-2">
          <div ref="exportContainer" class="relative">
            <BaseButton
              size="sm"
              :loading="exportingPdf || exportingAll"
              :aria-expanded="exportOpen"
              @click="toggleExport()"
            >
              Exportieren
              <ChevronDown class="h-4 w-4" aria-hidden="true" />
            </BaseButton>
            <div
              v-if="exportOpen"
              class="absolute right-0 top-full z-20 mt-1 w-56 rounded-card border border-default bg-surface p-1 shadow-lg"
              role="menu"
              aria-label="Exportieren"
            >
              <button
                type="button"
                role="menuitem"
                :class="menuItemClass"
                @click="runExport(copyAnonymized)"
              >
                <Copy class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
                Kopieren
              </button>
              <button
                type="button"
                role="menuitem"
                :class="menuItemClass"
                @click="runExport(downloadAnonymized)"
              >
                <Download class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
                Als Textdatei (.txt)
              </button>
              <button
                v-if="canExportPdf"
                type="button"
                role="menuitem"
                :class="menuItemClass"
                @click="runExport(downloadRedactedPdf)"
              >
                <FileDown class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
                Als PDF
              </button>
              <button
                v-if="canExportAll"
                type="button"
                role="menuitem"
                :class="menuItemClass"
                @click="runExport(downloadAllDocuments)"
              >
                <Archive class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
                Alle Dokumente (.zip)
              </button>
              <!-- Export option (does not close the menu): keep original
                   filenames instead of "anonymisiert.*". -->
              <div class="my-1 border-t border-default" role="separator"></div>
              <label
                class="flex cursor-pointer items-start gap-2 rounded-card px-3 py-2 transition-colors hover:bg-surface-muted"
              >
                <input
                  type="checkbox"
                  class="mt-0.5 h-3.5 w-3.5 shrink-0 accent-primary"
                  :checked="settings.keepFilenames"
                  @change="settings.setKeepFilenames(($event.target as HTMLInputElement).checked)"
                />
                <span class="text-sm text-content">
                  Dateinamen beibehalten
                  <span class="block text-xs text-content-subtle">
                    Vorsicht: Dateinamen können personenbezogene Daten enthalten.
                  </span>
                </span>
              </label>
            </div>
          </div>
          <BaseButton size="sm" variant="secondary" @click="session.reset()">
            {{ resetLabel }}
          </BaseButton>
        </div>
      </div>

      <!-- Subdued meta line: batch progress, plus diagnostics in expert mode. -->
      <p v-if="metaLine" class="text-xs text-content-subtle" aria-live="polite">{{ metaLine }}</p>

      <!-- View switcher: toggle 1–3 panels open concurrently. Default mode
           consolidates the result panels into one "Ergebnis" chip; expert
           mode offers all four panels individually. -->
      <div class="flex flex-wrap items-center gap-3">
        <div
          class="inline-flex flex-wrap gap-1 rounded-card bg-surface-muted p-1"
          role="group"
          aria-label="Ansichten wählen"
        >
          <button
            v-for="panel in switcherPanels"
            :key="panel.id"
            type="button"
            :aria-pressed="isPanelActive(panel.id)"
            class="inline-flex items-center gap-1.5 rounded-card px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :class="
              isPanelActive(panel.id)
                ? 'bg-surface text-content shadow-sm'
                : 'text-content-muted hover:text-content'
            "
            @click="togglePanelChip(panel.id)"
          >
            <Check
              v-if="isPanelActive(panel.id)"
              class="h-3.5 w-3.5 text-primary"
              aria-hidden="true"
            />
            {{ panel.label }}
          </button>
        </div>
      </div>

      <!-- Panels: equal-height cards in a responsive grid. Reading order
           follows the transformation: Original → Quellprüfung → Ergebnis. -->
      <div class="grid items-start gap-4" :class="gridClass">
        <!-- Original document: PDF sources render the untouched upload, text
             sources the extracted source text. -->
        <section v-if="isVisible('original')" :class="panelCardClass">
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
        <section v-if="isVisible('source')" :class="panelCardClass">
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
             override re-run, so it always mirrors the text result). The area
             editor draws additional blackout regions (signatures, logos) on
             the ORIGINAL pages; they apply to the export and this preview. -->
        <section v-if="isVisible('pdf')" :class="panelCardClass">
          <header class="shrink-0 border-b border-default bg-surface-muted px-4 py-2.5">
            <div class="flex items-center justify-between gap-2">
              <h3 class="text-sm font-semibold text-content">Geschwärztes PDF</h3>
              <button
                v-if="session.sourceFile !== null"
                type="button"
                :aria-pressed="areaEditing"
                class="inline-flex items-center gap-1.5 rounded-card px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="
                  areaEditing
                    ? 'bg-surface text-content shadow-sm'
                    : 'text-content-muted hover:text-content'
                "
                @click="areaEditing = !areaEditing"
              >
                <EyeOff class="h-3.5 w-3.5" aria-hidden="true" />
                Bereiche schwärzen
                <span v-if="session.redactAreas.length > 0">
                  ({{ session.redactAreas.length }})
                </span>
              </button>
            </div>
            <p v-if="result.source_type === 'pdf-ocr'" class="text-xs text-content-subtle">
              Rekonstruiertes Dokument – Layout angenähert, Originalpixel werden verworfen.
            </p>
          </header>
          <PdfAreaEditor v-if="areaEditing" class="min-h-0 flex-1" @done="areaEditing = false" />
          <div
            v-else-if="session.pdfPreviewLoading"
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
        <section v-if="isVisible('anonymized')" :class="panelCardClass">
          <header :class="panelHeaderClass">
            <h3 class="text-sm font-semibold text-content">Anonymisierter Text</h3>
          </header>
          <div
            class="min-h-0 flex-1 overflow-y-auto p-6 font-sans text-[15px] leading-relaxed whitespace-pre-wrap break-words text-content"
            v-text="result.anonymized_text"
          ></div>
        </section>
      </div>

      <!-- Entity summary: one quiet line; each type steps through its finds. -->
      <section
        class="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm"
        aria-label="Erkannte Entitäten"
      >
        <template v-if="session.entityCounts.length > 0">
          <span class="text-content-muted">{{ entitySummaryIntro }}</span>
          <template v-for="(item, index) in session.entityCounts" :key="item.type">
            <span v-if="index > 0" class="text-content-subtle" aria-hidden="true">·</span>
            <button
              type="button"
              class="rounded-sm font-medium text-content transition-colors hover:text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              :title="`Nächste Stelle vom Typ ${entityTypeLabel(item.type)} anzeigen`"
              @click="cycleEntityType(item.type)"
            >
              {{ entityTypeLabel(item.type) }} {{ item.count }}
            </button>
          </template>
        </template>
        <span v-else class="text-content-subtle">Keine personenbezogenen Stellen erkannt.</span>
      </section>

      <!-- Warnings (collapsed when the validation passed). Keyed per document
           so the open state resets on switch. -->
      <WarningsList
        :key="doc.id"
        :validation-warnings="result.validation.warnings"
        :general-warnings="result.warnings"
        :initially-open="result.validation.status !== 'PASS'"
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
import { computed, ref, watch } from 'vue'
import { strToU8, zipSync } from 'fflate'
import {
  AlertTriangle,
  Archive,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  Download,
  EyeOff,
  FileDown,
  FileX,
  XCircle,
} from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import DocumentBar from '@/components/anonymizer/DocumentBar.vue'
import EntityHighlights from '@/components/anonymizer/EntityHighlights.vue'
import EntityDetailPanel from '@/components/anonymizer/EntityDetailPanel.vue'
import PdfAreaEditor from '@/components/anonymizer/PdfAreaEditor.vue'
import ProcessingCard from '@/components/anonymizer/ProcessingCard.vue'
import WarningsList from '@/components/anonymizer/WarningsList.vue'
import { useSessionStore } from '@/stores/session'
import type { ResultPanelId } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { usePopover } from '@/composables/usePopover'
import { useToast } from '@/composables/useToast'
import { useFileDownload } from '@/composables/useFileDownload'
import { anonymizeApi } from '@/services/anonymizeApi'
import { extractPdfExportErrorMessage } from '@/utils/errors'
import { getBannerClass } from '@/utils/statusStyles'
import { entityTypeLabel, sourceTypeLabel } from '@/utils/entityLabels'
import type { EntityType } from '@/types/anonymizer'

const session = useSessionStore()
const settings = useSettingsStore()
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
const menuItemClass =
  'flex w-full items-center gap-2 rounded-card px-3 py-2 text-left text-sm text-content transition-colors hover:bg-surface-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring'

const isPdfSource = computed(
  () => result.value?.source_type === 'pdf' || result.value?.source_type === 'pdf-ocr',
)

/** Area-redaction editor in the Original panel (per view; off on doc switch). */
const areaEditing = ref(false)
watch(
  () => session.activeDocumentId,
  () => {
    areaEditing.value = false
  },
)

// ---------------------------------------------------------------------------
// Header: status headline + export menu
// ---------------------------------------------------------------------------

const statusHeadline = computed(() => {
  const validation = result.value?.validation
  if (!validation) return ''
  switch (validation.status) {
    case 'PASS':
      return 'Geprüft – keine Auffälligkeiten'
    case 'REVIEW_REQUIRED': {
      const count = validation.warnings.length
      return count === 1 ? 'Prüfbedarf – 1 Hinweis' : `Prüfbedarf – ${count} Hinweise`
    }
    default:
      return 'Prüfung fehlgeschlagen'
  }
})

const statusIcon = computed(() => {
  switch (result.value?.validation.status) {
    case 'PASS':
      return CheckCircle2
    case 'REVIEW_REQUIRED':
      return AlertTriangle
    default:
      return XCircle
  }
})

const statusIconClass = computed(() => {
  switch (result.value?.validation.status) {
    case 'PASS':
      return 'text-green-600 dark:text-green-400'
    case 'REVIEW_REQUIRED':
      return 'text-amber-500 dark:text-amber-400'
    default:
      return 'text-red-600 dark:text-red-400'
  }
})

/** Diagnostics (source type, timing) are expert-only; batch progress is not. */
const metaLine = computed<string | null>(() => {
  const parts: string[] = []
  if (settings.expertMode && result.value) {
    parts.push(sourceTypeLabel(result.value.source_type))
    parts.push(`Verarbeitet in ${Math.round(result.value.timing_ms.total)} ms`)
  }
  if (batchSummary.value) parts.push(batchSummary.value)
  return parts.length > 0 ? parts.join(' · ') : null
})

const exportContainer = ref<HTMLElement | null>(null)
const { open: exportOpen, toggle: toggleExport, close: closeExport } = usePopover(exportContainer)

function runExport(action: () => unknown): void {
  closeExport()
  void action()
}

// ---------------------------------------------------------------------------
// View switcher: simple single-select (+ original comparison) vs. the free
// expert combination (up to three panels, oldest evicted).
// ---------------------------------------------------------------------------

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

/** The "Ergebnis" panel of default mode: redacted PDF for PDFs, else text. */
const simpleResultPanel = computed<ResultPanelId>(() => (isPdfSource.value ? 'pdf' : 'anonymized'))

/** Default mode consolidates pdf+anonymized into one "Ergebnis" chip. */
const simplePanels = computed<{ id: ResultPanelId; label: string }[]>(() => [
  { id: 'original', label: 'Original' },
  { id: 'source', label: 'Prüfung' },
  { id: simpleResultPanel.value, label: 'Ergebnis' },
])

const switcherPanels = computed(() =>
  settings.expertMode ? availablePanels.value : simplePanels.value,
)

/** The result-shaped panel that is currently active, if any. */
const activeResultPanel = computed<ResultPanelId | undefined>(() =>
  session.activePanels.find((panel) => panel === 'pdf' || panel === 'anonymized'),
)

function isPanelActive(id: ResultPanelId): boolean {
  if (settings.expertMode || id === 'original' || id === 'source') {
    return session.activePanels.includes(id)
  }
  // Default mode: the "Ergebnis" chip is active when ANY result panel is
  // (e.g. an 'anonymized' left over from expert mode on a PDF source).
  return activeResultPanel.value !== undefined
}

function togglePanelChip(id: ResultPanelId): void {
  if (settings.expertMode || id === 'original' || id === 'source') {
    session.togglePanel(id)
    return
  }
  // Default mode "Ergebnis": toggle off whichever result panel is active.
  session.togglePanel(activeResultPanel.value ?? id)
}

/**
 * The panels the grid renders. Default mode normalizes leftovers from expert
 * mode (never two result panels at once) and fixes the reading order.
 */
const visiblePanels = computed<ResultPanelId[]>(() => {
  if (settings.expertMode) return session.activePanels
  const panels: ResultPanelId[] = []
  if (session.activePanels.includes('original')) panels.push('original')
  if (session.activePanels.includes('source')) panels.push('source')
  if (activeResultPanel.value !== undefined) panels.push(activeResultPanel.value)
  return panels
})

function isVisible(id: ResultPanelId): boolean {
  return visiblePanels.value.includes(id)
}

const gridClass = computed(() => {
  switch (visiblePanels.value.length) {
    case 1:
      return 'grid-cols-1'
    case 2:
      return 'grid-cols-1 lg:grid-cols-2'
    default:
      // Three columns only on very wide screens; two columns wrapping at lg.
      return 'grid-cols-1 lg:grid-cols-2 xl:grid-cols-3'
  }
})

/** Bring the source review on screen (both modes: just activate the panel). */
function showSourcePanel(): void {
  session.activatePanel('source')
}

// ---------------------------------------------------------------------------
// Entity summary: clicking a type steps through its finds in the source view.
// ---------------------------------------------------------------------------

const entitySummaryIntro = computed(() => {
  const count = result.value?.entities.length ?? 0
  return count === 1 ? '1 Stelle erkannt:' : `${count} Stellen erkannt:`
})

function cycleEntityType(type: EntityType): void {
  const entities = result.value?.entities ?? []
  const indices: number[] = []
  entities.forEach((entity, index) => {
    if (entity.entity_type === type) indices.push(index)
  })
  if (indices.length === 0) return
  const position =
    session.selectedEntityIndex === null ? -1 : indices.indexOf(session.selectedEntityIndex)
  showSourcePanel()
  session.selectEntity(indices[(position + 1) % indices.length]!)
}

// ---------------------------------------------------------------------------
// Batch summary / reset
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Export actions
// ---------------------------------------------------------------------------

async function copyAnonymized() {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(result.value.anonymized_text)
    toast.success('Anonymisierter Text in die Zwischenablage kopiert.')
  } catch {
    toast.error('Kopieren fehlgeschlagen. Bitte markieren und manuell kopieren.')
  }
}

/** Base name derived from the ORIGINAL upload (pasted text has none). */
const exportBase = computed<string | null>(() => {
  const entry = doc.value
  if (!entry || entry.file === null) return null
  const base = entry.name.replace(/\.[^.]+$/, '')
  return base.length > 0 ? base : null
})

/** "anonymisiert.<ext>" by default; the original base name when opted in. */
function exportFilename(extension: 'txt' | 'pdf'): string {
  return settings.keepFilenames && exportBase.value !== null
    ? `${exportBase.value}.${extension}`
    : `anonymisiert.${extension}`
}

function downloadAnonymized() {
  if (!result.value) return
  downloadBlob(result.value.anonymized_text, exportFilename('txt'), 'text/plain;charset=utf-8')
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
    downloadBlob(entry.pdfPreviewBlob, exportFilename('pdf'))
    return
  }
  const overrides = [...entry.overrides.values()]
  exportingPdf.value = true
  try {
    await downloadFromApi(
      () =>
        anonymizeApi.exportPdf(
          file,
          requestId,
          overrides,
          entry.policy,
          entry.rules,
          entry.redactAreas,
        ),
      exportFilename('pdf'),
    )
  } catch (err) {
    toast.error(await extractPdfExportErrorMessage(err))
  } finally {
    exportingPdf.value = false
  }
}

/** Finished documents of the batch (ZIP export). */
const doneDocuments = computed(() =>
  session.documents.filter((entry) => entry.status === 'done' && entry.result !== null),
)

/** "Alle Dokumente (.zip)" only makes sense for batches with ≥ 2 results. */
const canExportAll = computed(() => doneDocuments.value.length > 1)

const exportingAll = ref(false)

/**
 * Bundle every finished document into one ZIP: the anonymized text always,
 * plus the redacted PDF where its preview blob is already in memory (it
 * mirrors all current overrides/areas). Built entirely client-side.
 */
async function downloadAllDocuments() {
  if (exportingAll.value) return
  exportingAll.value = true
  try {
    const files: Record<string, Uint8Array> = {}
    const used = new Set<string>()
    const uniqueName = (name: string): string => {
      let candidate = name
      let counter = 2
      while (used.has(candidate)) {
        const dot = name.lastIndexOf('.')
        candidate = `${name.slice(0, dot)}-${counter}${name.slice(dot)}`
        counter += 1
      }
      used.add(candidate)
      return candidate
    }
    // ZIP entries always carry the base name (needed to tell 100 files
    // apart); the opt-in only drops the ".anonymisiert" infix.
    const infix = settings.keepFilenames ? '' : '.anonymisiert'
    for (const entry of doneDocuments.value) {
      if (!entry.result) continue
      const base = entry.name.replace(/\.[^.]+$/, '') || 'dokument'
      files[uniqueName(`${base}${infix}.txt`)] = strToU8(entry.result.anonymized_text)
      if (entry.pdfPreviewBlob !== null && !entry.pdfPreviewLoading) {
        files[uniqueName(`${base}${infix}.pdf`)] = new Uint8Array(
          await entry.pdfPreviewBlob.arrayBuffer(),
        )
      }
    }
    const zipped = zipSync(files)
    downloadBlob(new Blob([zipped]), 'anonymisiert.zip', 'application/zip')
    toast.success(`${Object.keys(files).length} Dateien als ZIP heruntergeladen.`)
  } catch {
    toast.error('Das ZIP-Archiv konnte nicht erstellt werden.')
  } finally {
    exportingAll.value = false
  }
}

/** "Im Text anzeigen" from the warnings list: make sure the review is visible. */
function showWarningInSource() {
  showSourcePanel()
}
</script>
