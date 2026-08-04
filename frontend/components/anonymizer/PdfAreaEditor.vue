<template>
  <div class="flex min-h-0 flex-col">
    <!-- Toolbar: how-to hint, one-click image suggestions and the explicit
         way back to the preview. Every change applies immediately — "Fertig"
         just returns to the (already refreshed) redacted preview. -->
    <div
      class="shrink-0 space-y-1.5 border-b border-default bg-surface-muted px-4 py-2 text-xs text-content-muted"
    >
      <div class="flex items-start justify-between gap-3">
        <p>
          Angezeigt werden die Originalseiten. Ziehen Sie ein Rechteck über einen Bereich
          (z.&nbsp;B. Unterschrift, Logo oder Stempel), um ihn zusätzlich zu schwärzen – Klick auf
          einen Bereich entfernt ihn wieder. Jede Änderung wird sofort übernommen.
        </p>
        <BaseButton size="sm" class="shrink-0" @click="emit('done')">
          <Check class="h-3.5 w-3.5" aria-hidden="true" />
          Fertig
        </BaseButton>
      </div>
      <div
        v-if="imageBoxCount > 0 || session.pdfPagesTruncated"
        class="flex flex-wrap items-center gap-2"
      >
        <BaseButton v-if="imageBoxCount > 0" size="sm" variant="secondary" @click="markAllImages">
          <ImageOff class="h-3.5 w-3.5" aria-hidden="true" />
          Alle Bilder schwärzen ({{ imageBoxCount }})
        </BaseButton>
        <span v-if="session.pdfPagesTruncated" class="text-amber-700 dark:text-amber-300">
          Nur die ersten {{ session.pdfPages?.length }} Seiten werden angezeigt.
        </span>
      </div>
    </div>

    <div
      v-if="session.pdfPagesLoading"
      class="flex flex-1 items-center justify-center gap-2 p-4 text-sm text-content-subtle"
      aria-live="polite"
    >
      <LoadingSpinner size="small" color="gray" inline label="" />
      Seiten werden gerendert …
    </div>
    <div v-else-if="session.pdfPagesError" class="space-y-3 p-4">
      <p class="rounded-card px-3 py-2 text-sm" :class="getBannerClass('red')">
        {{ session.pdfPagesError }}
      </p>
      <BaseButton size="sm" variant="secondary" @click="session.loadPdfPages()">
        Erneut versuchen
      </BaseButton>
    </div>

    <!-- Pages with drawing overlay. All coordinates are normalized 0–1000
         (top-left origin), rendered as percentages of the page wrapper. -->
    <div v-else class="min-h-0 flex-1 space-y-4 overflow-y-auto bg-surface-sunken p-4">
      <div
        v-for="page in session.pdfPages ?? []"
        :key="page.page"
        class="relative mx-auto max-w-3xl cursor-crosshair touch-none select-none bg-white shadow-sm"
        @pointerdown="onPointerDown($event, page.page)"
        @pointermove="onPointerMove($event)"
        @pointerup="onPointerUp($event, page.page)"
        @pointercancel="drawing = null"
      >
        <img :src="page.image" :alt="`Seite ${page.page}`" class="block w-full" draggable="false" />

        <!-- Existing areas: click to remove. -->
        <button
          v-for="area in areasOn(page.page)"
          :key="area.index"
          type="button"
          class="group absolute bg-black/85 transition-colors hover:bg-black/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :style="rectStyle(area)"
          :aria-label="`Geschwärzten Bereich auf Seite ${page.page} entfernen`"
          title="Bereich entfernen"
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
import { computed, onMounted, ref } from 'vue'
import { Check, ImageOff, X } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { getBannerClass } from '@/utils/statusStyles'

const emit = defineEmits<{
  (e: 'done'): void
}>()

const session = useSessionStore()
const toast = useToast()

/** Minimum drag size (normalized units) — below counts as an accidental click. */
const MIN_AREA_SIZE = 8

onMounted(() => {
  void session.loadPdfPages()
})

const imageBoxCount = computed(() =>
  (session.pdfPages ?? []).reduce((sum, page) => sum + page.image_boxes.length, 0),
)

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
    toast.info('Alle erkannten Bilder sind bereits geschwärzt.')
  } else {
    toast.success(
      added === 1 ? '1 Bild zum Schwärzen markiert.' : `${added} Bilder zum Schwärzen markiert.`,
    )
  }
}
</script>
