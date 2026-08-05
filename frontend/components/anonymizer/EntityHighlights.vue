<template>
  <div class="flex min-h-0 flex-col">
    <!-- Compact legend: colored dot + label per status, never color alone.
         Only statuses that actually occur in the document are listed. -->
    <div
      v-if="legend.length > 0"
      class="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-default bg-surface-muted px-4 py-2 text-xs text-content-muted"
      :aria-label="t('highlights.legend_label')"
    >
      <span v-for="item in legend" :key="item.label" class="inline-flex items-center gap-1.5">
        <span class="h-2 w-2 rounded-full" :class="item.dotClass" aria-hidden="true"></span>
        {{ item.label }}
      </span>
    </div>

    <!-- Source text with highlighted entity marks. Selecting arbitrary text
         offers a "Schwärzen" popover for manual redaction. -->
    <div
      ref="textContainer"
      class="relative min-h-0 flex-1 overflow-y-auto p-6 font-sans text-[15px] leading-relaxed whitespace-pre-wrap break-words text-content"
      @scroll.passive="hidePopover"
    >
      <template v-for="segment in segments" :key="segment.key">
        <button
          v-if="segment.entityIndex !== null"
          type="button"
          class="inline cursor-pointer rounded-md px-1 py-0.5 box-decoration-clone transition-shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :class="[
            entityHighlightClass(entityAt(segment.entityIndex).status),
            segment.entityIndex === selectedIndex ? 'ring-2 ring-ring shadow-sm' : '',
          ]"
          :title="markTitle(segment.entityIndex)"
          :aria-label="markAriaLabel(segment.entityIndex)"
          :data-entity-index="segment.entityIndex"
          @click="emit('select', segment.entityIndex)"
        >
          <!--
            v-text keeps the segment text free of template whitespace — the
            container is whitespace-pre-wrap, so stray indentation would render.
            data-start (code point offset of the segment's first character)
            anchors selection-boundary → source-offset mapping; it sits on the
            span holding EXACTLY the segment text, not on the button (which may
            also contain badge text).
          -->
          <span :data-start="segment.start" v-text="segment.text"></span>
          <!-- Replacement/type badge only on the SELECTED entity (all other
               marks expose the same info via the title tooltip). -->
          <span
            v-if="segment.showEntityLabel && segment.entityIndex === selectedIndex"
            class="ml-1 rounded px-1 align-super text-[10px] font-semibold"
            :class="getPillClass(entityStatusPillColor(entityAt(segment.entityIndex).status))"
            v-text="badgeText(segment.entityIndex)"
          ></span>
          <!-- User-overridden entity marker (metadata.overridden). The status
               is also in the tooltip/aria label, never the dot alone. -->
          <span
            v-if="segment.showEntityLabel && isOverridden(segment.entityIndex)"
            class="ml-0.5 inline-block h-1.5 w-1.5 rounded-full bg-purple-500 align-middle dark:bg-purple-400"
            aria-hidden="true"
          ></span>
        </button>
        <mark
          v-else-if="segment.warning"
          class="rounded-md px-1 py-0.5 box-decoration-clone"
          :class="WARNING_HIGHLIGHT_CLASS"
          :title="t('highlights.warning_title')"
        >
          <span :data-start="segment.start" v-text="segment.text"></span>
        </mark>
        <span v-else :data-start="segment.start" v-text="segment.text"></span>
      </template>

      <!-- Floating "Schwärzen" pill near the end of a valid text selection.
           whitespace-normal resets the container's pre-wrap so template
           whitespace never renders inside the pill. -->
      <div
        v-if="pendingSelection"
        ref="popoverEl"
        class="absolute z-10 whitespace-normal"
        :style="{ top: `${pendingSelection.top}px`, left: `${pendingSelection.left}px` }"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-3 py-1.5 text-xs font-medium whitespace-nowrap text-white shadow-lg transition-colors hover:bg-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 dark:bg-slate-700 dark:hover:bg-slate-600"
          :disabled="rerunning"
          :aria-label="t('highlights.redact_label')"
          @mousedown.prevent
          @click="applyManualRedaction"
        >
          <EyeOff class="h-3.5 w-3.5" aria-hidden="true" />
          {{ t('highlights.redact') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { EyeOff } from '@lucide/vue'
import { buildHighlightSegments } from '@/utils/textSegments'
import { getPillClass } from '@/utils/statusStyles'
import { overrideKey, useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { extractApiErrorMessage } from '@/utils/errors'
import {
  ENTITY_STATUSES,
  ENTITY_DOT_CLASSES,
  WARNING_DOT_CLASS,
  WARNING_HIGHLIGHT_CLASS,
  entityHighlightClass,
  entityStatusLabel,
  entityStatusPillColor,
  entityTypeLabel,
} from '@/utils/entityLabels'
import type { AnonymizedEntity, ValidationWarning } from '@/types/anonymizer'

interface Props {
  sourceText: string
  entities: AnonymizedEntity[]
  warnings: ValidationWarning[]
  selectedIndex: number | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'select', index: number): void
}>()

const { t } = useI18n()
const session = useSessionStore()
const toast = useToast()

const segments = computed(() =>
  buildHighlightSegments(props.sourceText, props.entities, props.warnings),
)

function entityAt(index: number): AnonymizedEntity {
  // Segments are derived from props.entities, so the index is always valid.
  return props.entities[index]!
}

function isOverridden(index: number): boolean {
  return entityAt(index).metadata?.overridden === true
}

function isUserManual(index: number): boolean {
  return entityAt(index).metadata?.user_manual === true
}

/** Type label for the tooltip/aria text; manual spans get a dedicated one. */
function markTypeLabel(index: number): string {
  return isUserManual(index)
    ? t('entity.manual_mark')
    : entityTypeLabel(entityAt(index).entity_type)
}

/** Native tooltip: "Person · [PERSON_1] · geändert". */
function markTitle(index: number): string {
  const entity = entityAt(index)
  const parts = [markTypeLabel(index), entity.replacement ?? entityStatusLabel(entity.status)]
  if (isOverridden(index)) parts.push(t('detail.changed_short'))
  return parts.join(' · ')
}

/** Accessible name of a mark — the status is never conveyed by color alone. */
function markAriaLabel(index: number): string {
  const params = {
    type: markTypeLabel(index),
    status: entityStatusLabel(entityAt(index).status),
  }
  return isOverridden(index)
    ? t('highlights.mark_label_overridden', params)
    : t('highlights.mark_label', params)
}

/** Superscript badge on the selected entity: replacement (or type). */
function badgeText(index: number): string {
  const entity = entityAt(index)
  return entity.replacement ?? markTypeLabel(index)
}

const legend = computed(() => {
  const present = new Set(props.entities.map((entity) => entity.status))
  const items = ENTITY_STATUSES.filter((status) => present.has(status)).map((status) => ({
    label: entityStatusLabel(status),
    dotClass: ENTITY_DOT_CLASSES[status],
  }))
  if (props.warnings.length > 0) {
    items.push({ label: t('highlights.warning_legend'), dotClass: WARNING_DOT_CLASS })
  }
  return items
})

// Keep the selected mark visible when the selection comes from outside the
// text (entity-summary type stepping in ResultView).
watch(
  () => props.selectedIndex,
  (index) => {
    if (index === null) return
    void nextTick(() => {
      textContainer.value
        ?.querySelector(`[data-entity-index="${index}"]`)
        ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
  },
)

// ---------------------------------------------------------------------------
// Manual selection-to-redact.
//
// Backend offsets are Unicode CODE POINTS into `source_text`, DOM selection
// offsets are UTF-16 code units. Every rendered segment carries `data-start`
// (its code point start offset), so a selection boundary maps to
// segmentStart + count of CODE POINTS before the boundary within the segment.
// ---------------------------------------------------------------------------

/** Manual selections longer than this are rejected with a toast hint. */
const MAX_MANUAL_SELECTION = 500
/** Estimated popover width used to keep the pill inside the container. */
const POPOVER_WIDTH = 110

const textContainer = ref<HTMLElement | null>(null)
const popoverEl = ref<HTMLElement | null>(null)

/** Trimmed code point offsets + popover position of the current selection. */
const pendingSelection = ref<{ start: number; end: number; top: number; left: number } | null>(null)

const rerunning = computed(() => session.rerunning)

function hidePopover(): void {
  pendingSelection.value = null
}

/** Code point start offset of the first `data-start` segment inside `node`. */
function firstSegmentStart(node: Node): number | null {
  if (!(node instanceof Element)) return null
  const segment = node.matches('[data-start]')
    ? (node as HTMLElement)
    : node.querySelector<HTMLElement>('[data-start]')
  if (!segment) return null
  const start = Number(segment.dataset.start)
  return Number.isFinite(start) ? start : null
}

/** Code point END offset of the last `data-start` segment inside `node`. */
function lastSegmentEnd(node: Node): number | null {
  if (!(node instanceof Element)) return null
  const nested = node.querySelectorAll<HTMLElement>('[data-start]')
  const segment = node.matches('[data-start]')
    ? (node as HTMLElement)
    : (nested[nested.length - 1] ?? null)
  if (!segment) return null
  const start = Number(segment.dataset.start)
  if (!Number.isFinite(start)) return null
  return start + Array.from(segment.textContent ?? '').length
}

/**
 * Map one selection boundary (node + UTF-16 offset) to a code point offset
 * into the source text, or null when the boundary lies outside the segments.
 */
function boundaryCodePointOffset(node: Node, offset: number): number | null {
  if (node.nodeType === Node.TEXT_NODE) {
    const segment = node.parentElement?.closest<HTMLElement>('[data-start]') ?? null
    if (!segment) return null
    const start = Number(segment.dataset.start)
    if (!Number.isFinite(start)) return null
    // Count CODE POINTS before the boundary — never UTF-16 units.
    return start + Array.from((node.textContent ?? '').slice(0, offset)).length
  }
  if (node instanceof Element) {
    // Element boundary (double/triple click, drag past the end): the boundary
    // sits before childNodes[offset]. Snap to the first segment at/after it,
    // falling back to the end of the last segment before it.
    const children = node.childNodes
    for (let i = offset; i < children.length; i++) {
      const start = firstSegmentStart(children[i]!)
      if (start !== null) return start
    }
    for (let i = Math.min(offset, children.length) - 1; i >= 0; i--) {
      const end = lastSegmentEnd(children[i]!)
      if (end !== null) return end
    }
  }
  return null
}

/** Evaluate the current selection on mouseup and show/hide the popover. */
function handleSelectionMouseUp(event: MouseEvent): void {
  // Releasing the mouse on the popover itself must not dismiss it.
  if (event.target instanceof Node && popoverEl.value?.contains(event.target)) return

  const container = textContainer.value
  const selection = window.getSelection()
  if (!container || !selection || selection.isCollapsed || selection.rangeCount === 0) {
    hidePopover()
    return
  }
  // Both boundaries must lie inside the highlights text container.
  const range = selection.getRangeAt(0) // ranges are always in document order
  if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) {
    hidePopover()
    return
  }

  const rawStart = boundaryCodePointOffset(range.startContainer, range.startOffset)
  const rawEnd = boundaryCodePointOffset(range.endContainer, range.endOffset)
  if (rawStart === null || rawEnd === null) {
    hidePopover()
    return
  }

  // Normalize direction and clamp to the text bounds.
  const codePoints = Array.from(props.sourceText)
  let start = Math.max(0, Math.min(codePoints.length, Math.min(rawStart, rawEnd)))
  let end = Math.max(0, Math.min(codePoints.length, Math.max(rawStart, rawEnd)))

  // Trim leading/trailing whitespace from the selection.
  while (start < end && /\s/u.test(codePoints[start]!)) start++
  while (end > start && /\s/u.test(codePoints[end - 1]!)) end--
  if (end <= start) {
    hidePopover()
    return
  }
  if (end - start > MAX_MANUAL_SELECTION) {
    toast.info(t('toast.selection_too_long'))
    hidePopover()
    return
  }

  // A selection that exactly matches a detected entity just selects it.
  const entityIndex = props.entities.findIndex(
    (entity) => entity.start === start && entity.end === end,
  )
  if (entityIndex !== -1) {
    emit('select', entityIndex)
    selection.removeAllRanges()
    hidePopover()
    return
  }
  // Defensive: never enqueue a duplicate override key.
  if (session.overrides.has(overrideKey({ start, end }))) {
    hidePopover()
    return
  }

  // Position the pill near the selection end, inside the scroll container.
  const containerRect = container.getBoundingClientRect()
  const rects = range.getClientRects()
  const anchorRect = rects.length > 0 ? rects[rects.length - 1]! : range.getBoundingClientRect()
  const left = Math.max(
    8,
    Math.min(
      anchorRect.right - containerRect.left + container.scrollLeft,
      container.clientWidth - POPOVER_WIDTH,
    ),
  )
  const top = anchorRect.bottom - containerRect.top + container.scrollTop + 6
  pendingSelection.value = { start, end, top, left }
}

/** "Schwärzen": add a REMOVE override for the selected region and re-run. */
async function applyManualRedaction(): Promise<void> {
  const pending = pendingSelection.value
  if (!pending || rerunning.value) return
  hidePopover()
  window.getSelection()?.removeAllRanges()
  try {
    await session.addManualRedaction(pending.start, pending.end)
  } catch (err) {
    toast.error(extractApiErrorMessage(err))
  }
}

function handleDocumentMouseDown(event: MouseEvent): void {
  // Any press outside the popover dismisses it (a new selection may re-open it).
  if (event.target instanceof Node && popoverEl.value?.contains(event.target)) return
  hidePopover()
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') hidePopover()
}

onMounted(() => {
  // Document-level mouseup so selections released OUTSIDE the container (or
  // clicks elsewhere) are handled too; boundaries are validated per event.
  document.addEventListener('mouseup', handleSelectionMouseUp)
  document.addEventListener('mousedown', handleDocumentMouseDown)
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('mouseup', handleSelectionMouseUp)
  document.removeEventListener('mousedown', handleDocumentMouseDown)
  document.removeEventListener('keydown', handleKeydown)
})
</script>
