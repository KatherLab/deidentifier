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
          :label="t('result.background_progress_label')"
        />
        <p class="text-xs text-content-subtle" aria-live="polite">
          {{
            t('result.background_progress', {
              done: session.batchSettledCount,
              total: session.documents.length,
            })
          }}
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
          {{ t('result.rerunning') }}
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
              {{ t('result.export.button') }}
              <ChevronDown class="h-4 w-4" aria-hidden="true" />
            </BaseButton>
            <div
              v-if="exportOpen"
              class="absolute right-0 top-full z-20 mt-1 w-56 rounded-card border border-default bg-surface p-1 shadow-lg"
              role="menu"
              :aria-label="t('result.export.button')"
            >
              <button
                type="button"
                role="menuitem"
                :class="menuItemClass"
                @click="runExport(copyAnonymized)"
              >
                <Copy class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
                {{ t('result.export.copy') }}
              </button>
              <button
                type="button"
                role="menuitem"
                :class="menuItemClass"
                @click="runExport(downloadAnonymized)"
              >
                <Download class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
                {{ t('result.export.txt') }}
              </button>
              <button
                v-if="canExportPdf"
                type="button"
                role="menuitem"
                :class="menuItemClass"
                @click="runExport(downloadRedactedPdf)"
              >
                <FileDown class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
                {{ t('result.export.pdf') }}
              </button>
              <button
                v-if="canExportAll"
                type="button"
                role="menuitem"
                :class="menuItemClass"
                @click="runExport(downloadAllDocuments)"
              >
                <Archive class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
                {{ t('result.export.zip') }}
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
                  {{ t('result.export.keep_filenames') }}
                  <span class="block text-xs text-content-subtle">
                    {{ t('result.export.keep_filenames_hint') }}
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

      <!-- The result is about to leave the server's memory. Non-blocking: the
           reviewer can keep working and extend when they get to it. Nothing is
           lost either way — an expired result is recomputed from the text the
           browser still holds — but the re-run costs a full detection pass. -->
      <div
        v-if="lifetime.isExpiring.value || lifetime.isExpired.value"
        class="flex flex-wrap items-center gap-3 rounded-card border border-amber-300 bg-amber-50 px-3 py-2 dark:border-amber-700/60 dark:bg-amber-900/30"
        role="status"
        aria-live="polite"
      >
        <AlertTriangle
          class="h-4 w-4 shrink-0 text-amber-700 dark:text-amber-300"
          aria-hidden="true"
        />
        <p class="text-sm text-amber-900 dark:text-amber-100">
          <template v-if="lifetime.isExpired.value">{{
            t('result.lifetime.expired_hint')
          }}</template>
          <template v-else>
            {{ t('result.lifetime.expiring', { time: lifetime.formatted.value }) }}
          </template>
        </p>
        <BaseButton
          v-if="canExtend"
          size="sm"
          variant="secondary"
          class="ml-auto"
          :loading="session.extendingResults"
          @click="session.extendResults()"
        >
          {{ t('result.lifetime.extend') }}
        </BaseButton>
        <p
          v-else-if="!lifetime.isExpired.value"
          class="ml-auto text-xs text-amber-800 dark:text-amber-200"
        >
          {{ t('result.lifetime.at_maximum') }}
        </p>
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
          :aria-label="t('result.panels.switcher_label')"
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
            <h3 class="text-sm font-semibold text-content">{{ t('result.panels.original') }}</h3>
          </header>
          <template v-if="isPdfSource">
            <iframe
              v-if="session.originalPreviewUrl"
              :src="session.originalPreviewUrl"
              :title="t('result.original.iframe_title')"
              class="min-h-0 w-full flex-1"
            ></iframe>
            <p v-else class="p-6 text-sm text-content-subtle">
              {{ t('result.original.unavailable') }}
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
            <h3 class="text-sm font-semibold text-content">{{ t('result.panels.source') }}</h3>
          </header>
          <EntityHighlights
            class="min-h-0 flex-1"
            :source-text="result.source_text"
            :entities="result.entities"
            :warnings="result.validation.warnings"
            :selected-indices="session.selectedEntityIndices"
            :focus-index="session.selectedEntityIndex"
            @select="session.selectEntity($event)"
            @toggle="session.toggleEntitySelection($event)"
            @range="session.selectEntityRange($event)"
            @clear="session.clearSelection()"
          >
            <!-- Anchored next to the marks, not at the foot of the card: one
                 selected entity → its details, several → the bulk actions. -->
            <template #actions>
              <EntityDetailPanel
                v-if="session.selectedEntity"
                :entity="session.selectedEntity"
                @close="session.clearSelection()"
              />
              <EntitySelectionBar v-else-if="session.selectedEntityIndices.length > 1" />
            </template>
          </EntityHighlights>
          <p
            v-if="session.selectedEntityIndices.length === 0"
            class="shrink-0 border-t border-default px-4 py-2.5 text-xs text-content-subtle"
          >
            {{ t('result.source.hint') }}
          </p>
        </section>

        <!-- Redacted-PDF preview (PDF sources only; refreshed after every
             override re-run, so it always mirrors the text result). The area
             editor draws additional blackout regions (signatures, logos) on
             the ORIGINAL pages; they apply to the export and this preview. -->
        <section v-if="isVisible('pdf')" :class="panelCardClass">
          <header class="shrink-0 border-b border-default bg-surface-muted px-4 py-2.5">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h3 class="text-sm font-semibold text-content">{{ t('result.panels.pdf') }}</h3>
              <!-- Two VIEWS of this one panel, not an on/off switch: opening
                   the editor replaces the preview, so the header shows both
                   sides and which one is showing. -->
              <div
                v-if="session.sourceFile !== null"
                role="group"
                :aria-label="t('result.pdf.view_label')"
                class="inline-flex items-center gap-0.5 rounded-card bg-surface-sunken p-0.5"
              >
                <button
                  type="button"
                  :aria-pressed="!areaEditing"
                  :class="pdfViewTabClass(!areaEditing)"
                  @click="areaEditing = false"
                >
                  {{ t('result.pdf.view_preview') }}
                </button>
                <button
                  type="button"
                  :aria-pressed="areaEditing"
                  :class="pdfViewTabClass(areaEditing)"
                  @click="areaEditing = true"
                >
                  <SquareDashedMousePointer class="h-3.5 w-3.5" aria-hidden="true" />
                  {{ t('result.pdf.view_areas') }}
                  <span
                    v-if="session.redactAreas.length > 0"
                    class="rounded-full bg-primary px-1.5 text-[11px] leading-4 font-semibold text-white"
                    :aria-label="
                      t(
                        'result.pdf.areas_badge_label',
                        { count: session.redactAreas.length },
                        session.redactAreas.length,
                      )
                    "
                  >
                    {{ session.redactAreas.length }}
                  </span>
                </button>
              </div>
            </div>
            <p v-if="result.source_type === 'pdf-ocr'" class="text-xs text-content-subtle">
              {{ t('result.pdf.reconstructed') }}
            </p>
          </header>
          <!-- The one place where this PDF differs from the text result: true
               redaction blacks out every occurrence of a redacted string, so a
               single kept occurrence stays covered here. Repeated from the
               warnings list on purpose — that list is collapsed when the
               validation passed, and this is where the reviewer will be looking
               when they wonder why it is still black. -->
          <p
            v-if="pdfPreserveNotice"
            class="shrink-0 border-b border-default px-4 py-2.5 text-xs"
            :class="getBannerClass('amber')"
            role="status"
          >
            {{ noticeMessage(pdfPreserveNotice) }}
          </p>
          <PdfAreaEditor v-if="areaEditing" class="min-h-0 flex-1" @done="areaEditing = false" />
          <template v-else>
            <div
              v-if="session.pdfPreviewLoading"
              class="flex flex-1 items-center justify-center gap-2 p-4 text-sm text-content-subtle"
              aria-live="polite"
            >
              <LoadingSpinner size="small" color="gray" inline label="" />
              {{ t('result.pdf.generating') }}
            </div>
            <div v-else-if="session.pdfPreviewError" class="space-y-3 p-4">
              <p class="rounded-card px-3 py-2 text-sm" :class="getBannerClass('red')">
                {{ session.pdfPreviewError }}
              </p>
              <BaseButton size="sm" variant="secondary" @click="session.refreshPdfPreview()">
                {{ t('common.retry') }}
              </BaseButton>
            </div>
            <iframe
              v-else-if="session.pdfPreviewUrl"
              :src="session.pdfPreviewUrl"
              :title="t('result.pdf.preview_title')"
              class="min-h-0 w-full flex-1"
            ></iframe>
            <p v-else class="min-h-0 flex-1 p-6 text-sm text-content-subtle">
              {{ t('result.pdf.no_preview') }}
            </p>
            <!-- What the text pipeline cannot do: signatures, stamps and logos
                 stay in the pixels. Say so here, where the reviewer sees them. -->
            <p
              v-if="session.sourceFile !== null"
              class="shrink-0 border-t border-default px-4 py-2.5 text-xs text-content-subtle"
            >
              <template v-if="session.redactAreas.length === 0">
                {{ t('result.pdf.areas_invite') }}
              </template>
              <template v-else>
                {{
                  t(
                    'result.pdf.areas_marked',
                    { count: session.redactAreas.length },
                    session.redactAreas.length,
                  )
                }}
              </template>
              {{ ' ' }}
              <button
                type="button"
                class="rounded-sm font-medium text-primary underline underline-offset-2 transition-colors hover:text-primary-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                @click="areaEditing = true"
              >
                {{
                  session.redactAreas.length === 0
                    ? t('result.pdf.areas_invite_action')
                    : t('result.pdf.areas_edit')
                }}
              </button>
            </p>
          </template>
        </section>

        <!-- Anonymized output as plain selectable text. -->
        <section v-if="isVisible('anonymized')" :class="panelCardClass">
          <header :class="panelHeaderClass">
            <h3 class="text-sm font-semibold text-content">
              {{ t('result.panels.anonymized') }}
            </h3>
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
        :aria-label="t('result.entities.section_label')"
      >
        <template v-if="session.entityCounts.length > 0">
          <span class="text-content-muted">{{ entitySummaryIntro }}</span>
          <template v-for="(item, index) in session.entityCounts" :key="item.type">
            <span v-if="index > 0" class="text-content-subtle" aria-hidden="true">·</span>
            <button
              type="button"
              class="rounded-sm font-medium text-content transition-colors hover:text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              :title="t('result.entities.cycle_title', { type: entityTypeLabel(item.type) })"
              @click="cycleEntityType(item.type)"
            >
              {{ entityTypeLabel(item.type) }} {{ item.count }}
            </button>
          </template>
        </template>
        <span v-else class="text-content-subtle">{{ t('result.entities.none') }}</span>
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
            {{ doc.error ?? t('result.failed') }}
          </p>
          <BaseButton variant="secondary" @click="session.retryDocument(doc.id)">
            {{ t('common.retry') }}
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
import { useI18n } from 'vue-i18n'
import { strToU8, zipSync } from 'fflate'
import {
  AlertTriangle,
  Archive,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  Download,
  FileDown,
  FileX,
  SquareDashedMousePointer,
  XCircle,
} from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import DocumentBar from '@/components/anonymizer/DocumentBar.vue'
import EntityHighlights from '@/components/anonymizer/EntityHighlights.vue'
import EntityDetailPanel from '@/components/anonymizer/EntityDetailPanel.vue'
import EntitySelectionBar from '@/components/anonymizer/EntitySelectionBar.vue'
import PdfAreaEditor from '@/components/anonymizer/PdfAreaEditor.vue'
import ProcessingCard from '@/components/anonymizer/ProcessingCard.vue'
import WarningsList from '@/components/anonymizer/WarningsList.vue'
import { useSessionStore } from '@/stores/session'
import type { ResultPanelId } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { usePopover } from '@/composables/usePopover'
import { useResultLifetime } from '@/composables/useResultLifetime'
import { useToast } from '@/composables/useToast'
import { useFileDownload } from '@/composables/useFileDownload'
import { anonymizeApi } from '@/services/anonymizeApi'
import { extractPdfExportErrorMessage } from '@/utils/errors'
import { getBannerClass } from '@/utils/statusStyles'
import { entityTypeLabel, sourceTypeLabel } from '@/utils/entityLabels'
import { noticeMessage } from '@/utils/notices'
import type { EntityType, OutputLanguage } from '@/types/anonymizer'

const { t } = useI18n()
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

/** Which view of the redacted-PDF panel is showing (off on doc switch). */
const areaEditing = ref(false)
watch(
  () => session.activeDocumentId,
  () => {
    areaEditing.value = false
  },
)

/** Segmented control in the PDF panel header: preview ↔ area editor. */
function pdfViewTabClass(active: boolean): string {
  return [
    'inline-flex items-center gap-1.5 rounded-card px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
    active ? 'bg-surface text-content shadow-sm' : 'text-content-muted hover:text-content',
  ].join(' ')
}

// ---------------------------------------------------------------------------
// Result lifetime: how long the server still holds this document
// ---------------------------------------------------------------------------

/**
 * The batch's countdown — the same one the header chip shows, so the running
 * total is stated once. This view owns only the alarm: the banner that appears
 * in the final minute, where the reviewer is actually looking.
 */
const lifetime = useResultLifetime(() => session.resultsExpireAt)

/** The extension is only offered while there is something left to extend. */
const canExtend = computed(
  () => session.resultsCanExtend && !lifetime.isExpired.value && !session.rerunning,
)

// ---------------------------------------------------------------------------
// Header: status headline + export menu
// ---------------------------------------------------------------------------

const statusHeadline = computed(() => {
  const validation = result.value?.validation
  if (!validation) return ''
  switch (validation.status) {
    case 'PASS':
      return t('result.status.pass')
    case 'REVIEW_REQUIRED': {
      const count = validation.warnings.length
      return t('result.status.review', { count }, count)
    }
    default:
      return t('result.status.fail')
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
    parts.push(t('result.processed_in', { ms: Math.round(result.value.timing_ms.total) }))
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
    { id: 'original', label: t('result.panels.original') },
    { id: 'source', label: t('result.panels.source') },
  ]
  if (isPdfSource.value) panels.push({ id: 'pdf', label: t('result.panels.pdf') })
  panels.push({ id: 'anonymized', label: t('result.panels.anonymized') })
  return panels
})

/** The "Ergebnis" panel of default mode: redacted PDF for PDFs, else text. */
const simpleResultPanel = computed<ResultPanelId>(() => (isPdfSource.value ? 'pdf' : 'anonymized'))

/** Default mode consolidates pdf+anonymized into one "Ergebnis" chip. */
const simplePanels = computed<{ id: ResultPanelId; label: string }[]>(() => [
  { id: 'original', label: t('result.panels.original') },
  { id: 'source', label: t('result.panels.source_simple') },
  { id: simpleResultPanel.value, label: t('result.panels.result') },
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

/**
 * The backend's notice that this PDF blacks out passages the reviewer chose
 * to keep. Matched by CODE, never re-derived here: the condition depends on
 * how the exporter searches for text, which only the backend knows.
 */
const pdfPreserveNotice = computed(
  () =>
    result.value?.warnings.find((warning) => warning.code === 'pdf_preserve_not_honoured') ?? null,
)

/** Bring the source review on screen (both modes: just activate the panel). */
function showSourcePanel(): void {
  session.activatePanel('source')
}

// ---------------------------------------------------------------------------
// Entity summary: clicking a type steps through its finds in the source view.
// ---------------------------------------------------------------------------

const entitySummaryIntro = computed(() => {
  const count = result.value?.entities.length ?? 0
  return t('result.entities.intro', { count }, count)
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
  let summary = t('result.batch_summary', { done, total: docs.length })
  if (review > 0) summary += ` · ${t('result.batch_review', { count: review })}`
  if (failed > 0) summary += ` · ${t('result.batch_failed', { count: failed })}`
  return summary
})

const resetLabel = computed(() =>
  session.documents.length > 1 ? t('result.reset_many') : t('result.reset_one'),
)

// ---------------------------------------------------------------------------
// Export actions
// ---------------------------------------------------------------------------

async function copyAnonymized() {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(result.value.anonymized_text)
    toast.success(t('toast.copy_success'))
  } catch {
    toast.error(t('toast.copy_failed'))
  }
}

/**
 * A word for a file name, in the language the DOCUMENT was written in — not
 * the interface language. An exported file belongs to its document: a French
 * run stays "anonymise.txt" even when the reviewer has switched the UI to
 * English. The catalog is guaranteed to be loaded, because a language other
 * than the interface's can only be chosen in the policy editor, which preloads
 * all of them.
 */
function inDocumentLanguage(key: string, language: OutputLanguage): string {
  return t(key, {}, { locale: language })
}

/** The language the ACTIVE document was written in. */
const documentLanguage = computed<OutputLanguage>(
  () => result.value?.output_language ?? doc.value?.outputLanguage ?? 'de',
)

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
    : `${inDocumentLanguage('result.export.filename', documentLanguage.value)}.${extension}`
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
          // Both matter only on a backend cache miss, where the document is
          // re-extracted and re-transformed: without them the fallback would
          // skip the forced OCR and write German placeholders.
          entry.forceOcr,
          entry.outputLanguage,
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
    // apart); the opt-in only drops the ".anonymisiert" infix. The whole batch
    // shares one output language (captured at submit), so one lookup does.
    const language = documentLanguage.value
    const infix = settings.keepFilenames
      ? ''
      : `.${inDocumentLanguage('result.export.filename', language)}`
    for (const entry of doneDocuments.value) {
      if (!entry.result) continue
      const base =
        entry.name.replace(/\.[^.]+$/, '') ||
        inDocumentLanguage('result.export.document_fallback', language)
      files[uniqueName(`${base}${infix}.txt`)] = strToU8(entry.result.anonymized_text)
      if (entry.pdfPreviewBlob !== null && !entry.pdfPreviewLoading) {
        files[uniqueName(`${base}${infix}.pdf`)] = new Uint8Array(
          await entry.pdfPreviewBlob.arrayBuffer(),
        )
      }
    }
    const zipped = zipSync(files)
    downloadBlob(
      new Blob([zipped]),
      `${inDocumentLanguage('result.export.filename', language)}.zip`,
      'application/zip',
    )
    toast.success(t('toast.zip_downloaded', { count: Object.keys(files).length }))
  } catch {
    toast.error(t('toast.zip_failed'))
  } finally {
    exportingAll.value = false
  }
}

/** "Im Text anzeigen" from the warnings list: make sure the review is visible. */
function showWarningInSource() {
  showSourcePanel()
}
</script>
