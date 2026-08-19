<template>
  <div class="flex min-h-0 flex-col">
    <!-- Toolbar: how-to hint, one-click image suggestions and the explicit
         way back to the preview. Every change applies immediately — "Fertig"
         just returns to the (already refreshed) redacted preview. -->
    <div
      class="shrink-0 space-y-1.5 border-b border-default bg-surface-muted px-4 py-2 text-xs text-content-muted"
    >
      <div class="flex items-start justify-between gap-3">
        <p>{{ hint }}</p>
        <BaseButton size="sm" class="shrink-0" @click="emit('done')">
          <Check class="h-3.5 w-3.5" aria-hidden="true" />
          {{ t('common.done') }}
        </BaseButton>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <BaseButton
          v-if="!isReconstruction && imageBoxCount > 0"
          size="sm"
          variant="secondary"
          @click="markAllImages"
        >
          <ImageOff class="h-3.5 w-3.5" aria-hidden="true" />
          {{ t('areas.mark_all_images', { count: imageBoxCount }) }}
        </BaseButton>
        <!-- Native PDFs only: draw on the redacted preview instead of the
             original pages. Same page geometry, blackouts in the pixels. A
             scanned document has no such choice — see `isReconstruction`. -->
        <BaseButton
          v-if="!isReconstruction"
          size="sm"
          :variant="showRedacted ? 'primary' : 'secondary'"
          :disabled="redactedBlockedReason !== null"
          :aria-pressed="showRedacted"
          @click="session.setAreasShowRedacted(!showRedacted)"
        >
          <component :is="showRedacted ? EyeOff : Eye" class="h-3.5 w-3.5" aria-hidden="true" />
          {{ showRedacted ? t('areas.hide_redacted') : t('areas.show_redacted') }}
        </BaseButton>
        <span
          v-if="showsRedactedPages && renderingRedacted"
          class="inline-flex items-center gap-1.5"
          aria-live="polite"
        >
          <LoadingSpinner size="small" color="gray" inline label="" />
          {{ t('areas.redacted_loading') }}
        </span>
        <span v-else-if="toolbarWarning !== null" class="text-amber-700 dark:text-amber-300">
          {{ toolbarWarning }}
        </span>
        <span v-if="truncated" class="text-amber-700 dark:text-amber-300">
          {{ t('areas.truncated', { count: pages.length }) }}
        </span>
      </div>
    </div>

    <div
      v-if="surfaceLoading"
      class="flex flex-1 items-center justify-center gap-2 p-4 text-sm text-content-subtle"
      aria-live="polite"
    >
      <LoadingSpinner size="small" color="gray" inline label="" />
      {{ t('areas.rendering') }}
    </div>
    <!-- A scanned document has no fallback surface: its areas are applied to
         the reconstruction, so drawing them on the scan would place them
         somewhere else. Fail loudly instead. -->
    <div v-else-if="surfaceError !== null" class="space-y-3 p-4">
      <p class="rounded-card px-3 py-2 text-sm" :class="getBannerClass('red')">
        {{ surfaceError }}
      </p>
      <BaseButton size="sm" variant="secondary" @click="reloadSurface">
        {{ t('common.retry') }}
      </BaseButton>
    </div>

    <!-- Pages with drawing overlay. All coordinates are normalized 0–1000
         (top-left origin), rendered as percentages of the page wrapper. -->
    <div v-else class="min-h-0 flex-1 space-y-4 overflow-y-auto bg-surface-sunken p-4">
      <div
        v-for="page in pages"
        :key="page.page"
        class="relative mx-auto max-w-3xl cursor-crosshair touch-none select-none bg-white shadow-sm"
        @pointerdown="onPointerDown($event, page.page)"
        @pointermove="onPointerMove($event)"
        @pointerup="onPointerUp($event, page.page)"
        @pointercancel="drawing = null"
      >
        <img :src="pageImage(page)" :alt="pageAlt(page)" class="block w-full" draggable="false" />

        <!-- Existing areas: click to remove. -->
        <button
          v-for="area in areasOn(page.page)"
          :key="area.index"
          type="button"
          class="group absolute bg-black/85 transition-colors hover:bg-black/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :class="showsRedactedPages ? 'ring-1 ring-white/70 ring-inset' : ''"
          :style="rectStyle(area)"
          :aria-label="t('areas.remove_label', { page: page.page })"
          :title="t('areas.remove_title')"
          @pointerdown.stop
          @click="session.removeRedactArea(area.index)"
        >
          <X
            class="absolute top-0.5 right-0.5 hidden h-3.5 w-3.5 text-white group-hover:block"
            aria-hidden="true"
          />
        </button>

        <!-- Live rectangle while dragging. -->
        <div
          v-if="drawing && drawing.page === page.page"
          class="pointer-events-none absolute border-2 border-red-500 bg-black/40"
          :style="rectStyle(liveRect)"
        ></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, Eye, EyeOff, ImageOff, X } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { getBannerClass } from '@/utils/statusStyles'
import type { PdfPageRender } from '@/types/anonymizer'

const emit = defineEmits<{
  (e: 'done'): void
}>()

const { t } = useI18n()
const session = useSessionStore()
const toast = useToast()

/** Minimum drag size (normalized units) — below counts as an accidental click. */
const MIN_AREA_SIZE = 8

/**
 * Every drawn area regenerates the redacted preview, and each new preview
 * needs a new page render. Coalesce a burst of edits into one.
 */
const REDACTED_RENDER_DEBOUNCE_MS = 400

// ---------------------------------------------------------------------------
// The drawing surface.
//
// Native PDF: the original pages, optionally swapped for the redacted
// preview's pages so the automatic text redactions are visible while drawing.
// Both are the same geometry — the export blacks the areas out on the page
// itself.
//
// Scanned PDF: the redacted RECONSTRUCTION, always. Its export is re-typeset
// onto A4 and the original pixels are discarded, so the reconstruction is the
// page the areas are actually applied to; the scan (a different geometry) is
// the wrong thing to place them on. The scan itself stays one click away in
// the "Original" panel.
// ---------------------------------------------------------------------------

const isReconstruction = computed(() => session.result?.source_type === 'pdf-ocr')

onMounted(() => {
  // The reconstruction path never renders the scan — one big render saved.
  if (!isReconstruction.value) void session.loadPdfPages()
})

const imageBoxCount = computed(() =>
  (session.pdfPages ?? []).reduce((sum, page) => sum + page.image_boxes.length, 0),
)

const showRedacted = computed(() => session.areasShowRedacted)

/** True when what is on screen carries the automatic redactions. */
const showsRedactedPages = computed(() => isReconstruction.value || showRedacted.value)

const pages = computed<PdfPageRender[]>(() =>
  isReconstruction.value ? (session.pdfRedactedPages ?? []) : (session.pdfPages ?? []),
)

const truncated = computed(() =>
  isReconstruction.value ? session.pdfRedactedPagesTruncated : session.pdfPagesTruncated,
)

/** Why the native toggle cannot be offered yet, or null when it can. */
const redactedBlockedReason = computed<string | null>(() =>
  session.pdfPreviewBlob === null ? t('areas.redacted_unavailable') : null,
)

/** The redacted preview is being (re-)generated or rendered. */
const renderingRedacted = computed(
  () => session.pdfPreviewLoading || session.pdfRedactedPagesLoading,
)

/** Toggle unavailable, or on but still showing the originals. */
const toolbarWarning = computed<string | null>(() => {
  if (isReconstruction.value) return null
  if (redactedBlockedReason.value !== null) return redactedBlockedReason.value
  if (showRedacted.value && session.pdfRedactedPages === null) {
    return session.pdfRedactedPagesError
  }
  return null
})

const redactedImages = computed<Map<number, string>>(
  () => new Map((session.pdfRedactedPages ?? []).map((page) => [page.page, page.image])),
)

/** True when THIS page is currently showing its redacted render. */
function showsRedacted(page: PdfPageRender): boolean {
  return showRedacted.value && redactedImages.value.has(page.page)
}

function pageImage(page: PdfPageRender): string {
  // On the reconstruction path `pages` already IS the redacted render.
  if (isReconstruction.value) return page.image
  return showsRedacted(page) ? redactedImages.value.get(page.page)! : page.image
}

function pageAlt(page: PdfPageRender): string {
  if (isReconstruction.value) return t('areas.page_alt_reconstructed', { page: page.page })
  if (showsRedacted(page)) return t('areas.page_alt_redacted', { page: page.page })
  return t('areas.page_alt', { page: page.page })
}

const hint = computed(() => {
  if (isReconstruction.value) return t('areas.hint_reconstruction')
  return showRedacted.value ? t('areas.hint_redacted') : t('areas.hint')
})

// State of the surface itself. The reconstruction has no fallback: without
// its pages there is nothing safe to draw on, so its errors fill the panel
// instead of sitting in the toolbar.
const surfaceError = computed<string | null>(() => {
  if (!isReconstruction.value) return session.pdfPagesError
  if (pages.value.length > 0) return null
  return session.pdfRedactedPagesError ?? session.pdfPreviewError
})

const surfaceLoading = computed(() => {
  if (!isReconstruction.value) return session.pdfPagesLoading
  // No pages and nothing wrong: the preview or its render is still on its way.
  return pages.value.length === 0 && surfaceError.value === null
})

function reloadSurface(): void {
  if (isReconstruction.value) void session.refreshPdfPreview()
  else void session.loadPdfPages()
}

// Render the redacted pages when they are the surface (scanned) or the view
// is switched on (native), and again whenever a new preview supersedes them.
// The previous render stays on screen until the new one lands, so the pages
// never flash back to un-redacted.
let renderTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => [showsRedactedPages.value, session.pdfPreviewBlob] as const,
  ([needed]) => {
    if (renderTimer !== null) clearTimeout(renderTimer)
    if (!needed) return
    renderTimer = setTimeout(() => {
      void session.loadRedactedPdfPages()
    }, REDACTED_RENDER_DEBOUNCE_MS)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (renderTimer !== null) clearTimeout(renderTimer)
})

/** The active document's areas on ONE page, keeping their store index. */
function areasOn(page: number) {
  return session.redactAreas
    .map((area, index) => ({ ...area, index }))
    .filter((area) => area.page === page)
}

function rectStyle(rect: { x0: number; y0: number; x1: number; y1: number }) {
  // Normalized 0–1000 → percent of the page wrapper.
  return {
    left: `${rect.x0 / 10}%`,
    top: `${rect.y0 / 10}%`,
    width: `${(rect.x1 - rect.x0) / 10}%`,
    height: `${(rect.y1 - rect.y0) / 10}%`,
  }
}

// ---------------------------------------------------------------------------
// Drawing: pointer capture on the page wrapper; coordinates are derived from
// the wrapper's bounding box (same aspect ratio as the page).
// ---------------------------------------------------------------------------

interface DrawingState {
  page: number
  startX: number
  startY: number
  currentX: number
  currentY: number
}

const drawing = ref<DrawingState | null>(null)

const liveRect = computed(() => {
  const state = drawing.value
  if (!state) return { x0: 0, y0: 0, x1: 0, y1: 0 }
  return {
    x0: Math.min(state.startX, state.currentX),
    y0: Math.min(state.startY, state.currentY),
    x1: Math.max(state.startX, state.currentX),
    y1: Math.max(state.startY, state.currentY),
  }
})

/** Pointer position → normalized page coordinates (clamped to the page). */
function normalizedPoint(event: PointerEvent): { x: number; y: number } {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const x = ((event.clientX - rect.left) / rect.width) * 1000
  const y = ((event.clientY - rect.top) / rect.height) * 1000
  return {
    x: Math.min(Math.max(x, 0), 1000),
    y: Math.min(Math.max(y, 0), 1000),
  }
}

function onPointerDown(event: PointerEvent, page: number): void {
  if (event.button !== 0) return
  const point = normalizedPoint(event)
  drawing.value = { page, startX: point.x, startY: point.y, currentX: point.x, currentY: point.y }
  // Capture so the drag keeps tracking outside the page wrapper.
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent): void {
  const state = drawing.value
  if (!state) return
  const point = normalizedPoint(event)
  state.currentX = point.x
  state.currentY = point.y
}

function onPointerUp(event: PointerEvent, page: number): void {
  const state = drawing.value
  drawing.value = null
  if (!state || state.page !== page) return
  const point = normalizedPoint(event)
  const x0 = Math.min(state.startX, point.x)
  const y0 = Math.min(state.startY, point.y)
  const x1 = Math.max(state.startX, point.x)
  const y1 = Math.max(state.startY, point.y)
  if (x1 - x0 < MIN_AREA_SIZE || y1 - y0 < MIN_AREA_SIZE) return
  session.addRedactArea({ page, x0, y0, x1, y1 })
}

function markAllImages(): void {
  const added = session.addImageAreas()
  if (added === 0) {
    toast.info(t('toast.images_already_marked'))
  } else {
    toast.success(t('toast.images_marked', { count: added }, added))
  }
}
</script>
