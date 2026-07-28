<template>
  <section class="space-y-5">
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
        <BaseButton size="sm" @click="session.reset()">Neues Dokument</BaseButton>
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
          @click="togglePanel(panel.id)"
        >
          <Check v-if="isActive(panel.id)" class="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          {{ panel.label }}
        </button>
      </div>
      <span class="text-xs text-content-subtle">Bis zu 3 Ansichten gleichzeitig</span>
    </div>

    <!-- Panels: equal-height cards in a responsive grid. -->
    <div class="grid items-start gap-4" :class="gridClass">
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
        <p v-else class="shrink-0 border-t border-default px-4 py-2.5 text-xs text-content-subtle">
          Klicken Sie auf eine markierte Stelle, um Details und Aktionen anzuzeigen.
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
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Copy, Download, FileDown } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import EntityHighlights from '@/components/anonymizer/EntityHighlights.vue'
import EntityDetailPanel from '@/components/anonymizer/EntityDetailPanel.vue'
import WarningsList from '@/components/anonymizer/WarningsList.vue'
import { useSessionStore } from '@/stores/session'
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
import type { AnonymizeResponse } from '@/types/anonymizer'

interface Props {
  result: AnonymizeResponse
}

const props = defineProps<Props>()

const session = useSessionStore()
const toast = useToast()
const { downloadBlob, downloadFromApi } = useFileDownload()

/** Shared card chrome so all panel columns align at the same height. */
const panelCardClass =
  'flex h-[72vh] min-w-0 flex-col overflow-hidden rounded-card border border-default bg-surface'
const panelHeaderClass =
  'flex shrink-0 items-baseline gap-2 border-b border-default bg-surface-muted px-4 py-2.5'

const isPdfSource = computed(
  () => props.result.source_type === 'pdf' || props.result.source_type === 'pdf-ocr',
)

type PanelId = 'source' | 'pdf' | 'original' | 'anonymized'

const availablePanels = computed<{ id: PanelId; label: string }[]>(() => {
  const panels: { id: PanelId; label: string }[] = [{ id: 'source', label: 'Quellprüfung' }]
  if (isPdfSource.value) panels.push({ id: 'pdf', label: 'Geschwärztes PDF' })
  panels.push(
    { id: 'original', label: 'Original' },
    { id: 'anonymized', label: 'Anonymisierter Text' },
  )
  return panels
})

/**
 * Active panels in ACTIVATION order (oldest first) — enabling a 4th panel
 * evicts the oldest-activated one. The template renders them in a fixed
 * canonical order regardless. Quellprüfung is the default; PDF sources start
 * with the redacted-PDF preview alongside.
 */
const activePanels = ref<PanelId[]>(isPdfSource.value ? ['source', 'pdf'] : ['source'])

function isActive(id: PanelId): boolean {
  return activePanels.value.includes(id)
}

function activatePanel(id: PanelId): void {
  if (activePanels.value.includes(id)) return
  // The original-PDF object URL is created lazily on first activation.
  if (id === 'original' && isPdfSource.value) session.ensureOriginalPreviewUrl()
  activePanels.value.push(id)
  if (activePanels.value.length > 3) activePanels.value.shift()
}

function togglePanel(id: PanelId): void {
  const index = activePanels.value.indexOf(id)
  if (index === -1) {
    activatePanel(id)
    return
  }
  // At least one panel stays visible.
  if (activePanels.value.length === 1) return
  activePanels.value.splice(index, 1)
}

const gridClass = computed(() => {
  switch (activePanels.value.length) {
    case 1:
      return 'grid-cols-1'
    case 2:
      return 'grid-cols-1 lg:grid-cols-2'
    default:
      // Three columns only on very wide screens; two columns wrapping at lg.
      return 'grid-cols-1 lg:grid-cols-2 xl:grid-cols-3'
  }
})

async function copyAnonymized() {
  try {
    await navigator.clipboard.writeText(props.result.anonymized_text)
    toast.success('Anonymisierter Text in die Zwischenablage kopiert.')
  } catch {
    toast.error('Kopieren fehlgeschlagen. Bitte markieren und manuell kopieren.')
  }
}

function downloadAnonymized() {
  downloadBlob(props.result.anonymized_text, 'anonymisiert.txt', 'text/plain;charset=utf-8')
}

/**
 * Redacted-PDF export is only possible for PDF sources AND while the original
 * File is still held in memory (it is re-sent — the server stores nothing).
 */
const canExportPdf = computed(() => isPdfSource.value && session.sourceFile !== null)

const exportingPdf = ref(false)

/**
 * Download the redacted PDF with all current overrides applied. The preview
 * blob (if loaded) already reflects the current overrides, so it is reused
 * directly instead of re-requesting the export. The fallback request can take
 * up to a minute for scans on a backend cache miss, hence the loading state.
 */
async function downloadRedactedPdf() {
  const file = session.sourceFile
  if (!file || exportingPdf.value) return
  if (session.pdfPreviewBlob !== null && !session.pdfPreviewLoading) {
    downloadBlob(session.pdfPreviewBlob, 'anonymisiert.pdf')
    return
  }
  const requestId = props.result.request_id
  const overrides = [...session.overrides.values()]
  exportingPdf.value = true
  try {
    await downloadFromApi(
      () => anonymizeApi.exportPdf(file, requestId, overrides, session.policyOverrides),
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
  activatePanel('source')
}
</script>
