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
      <template v-for="(segment, index) in segments" :key="segment.key">
        <!--
          A SPAN, not a button, on purpose. Browsers force `display: inline-block`
          on form controls whatever the stylesheet says, and an inline-block box
          cannot be split across lines: a mark covering a line break (a manual
          selection dragged over one, or a multi-line address) rendered as one
          atomic two-line-tall box shoved into the middle of the paragraph, and
          a long mark near the right edge could not wrap at all. As a real
          inline box it fragments per line, which is what box-decoration-clone
          has always been here for. `role`/`tabindex`/`aria-pressed` keep the
          button semantics, and keyboard activation is wired below.
        -->
        <span
          v-if="segment.entityIndex !== null"
          role="button"
          tabindex="0"
          class="inline cursor-pointer py-0.5 box-decoration-clone transition-shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :class="[
            markEdgeClass(index),
            entityHighlightClass(entityAt(segment.entityIndex).status),
            isSelected(segment.entityIndex) ? 'ring-2 ring-ring shadow-sm' : '',
            segment.entityIndex === focusIndex ? 'ring-offset-1 ring-offset-surface' : '',
          ]"
          :title="markTitle(segment.entityIndex)"
          :aria-label="markAriaLabel(segment.entityIndex)"
          :aria-pressed="isSelected(segment.entityIndex)"
          :data-entity-index="segment.entityIndex"
          :data-selected="isSelected(segment.entityIndex) ? 'true' : undefined"
          @click="handleMarkClick(segment.entityIndex, $event)"
          @keydown.enter.prevent="handleMarkClick(segment.entityIndex, $event)"
          @keydown.space.prevent="handleMarkClick(segment.entityIndex, $event)"
        >
          <!--
            v-text keeps the segment text free of template whitespace — the
            container is whitespace-pre-wrap, so stray indentation would render.
            data-start (code point offset of the segment's first character)
            anchors selection-boundary → source-offset mapping; it sits on the
            span holding EXACTLY the segment text, not on the button (which may
            also contain badge text).
          -->
          <span
            :data-start="segment.start"
            :class="matchClass(segment)"
            :data-match-index="segment.matchIndex ?? undefined"
            :aria-current="segment.matchIndex === activeMatchIndex ? 'true' : undefined"
            v-text="segment.text"
          ></span>
          <!-- Replacement/type badge only on the SELECTED entity (all other
               marks expose the same info via the title tooltip). -->
          <span
            v-if="segment.showEntityLabel && isSelected(segment.entityIndex)"
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
        </span>
        <mark
          v-else-if="segment.warning"
          class="rounded-md px-1 py-0.5 box-decoration-clone"
          :class="WARNING_HIGHLIGHT_CLASS"
          :title="t('highlights.warning_title')"
        >
          <span
            :data-start="segment.start"
            :class="matchClass(segment)"
            :data-match-index="segment.matchIndex ?? undefined"
            :aria-current="segment.matchIndex === activeMatchIndex ? 'true' : undefined"
            v-text="segment.text"
          ></span>
        </mark>
        <span
          v-else
          :data-start="segment.start"
          :class="matchClass(segment)"
          :data-match-index="segment.matchIndex ?? undefined"
          :aria-current="segment.matchIndex === activeMatchIndex ? 'true' : undefined"
          v-text="segment.text"
        ></span>
      </template>

      <!--
        The actions for what is selected, anchored under the last-touched mark
        instead of at the foot of the card — the controls belong where the
        reviewer is reading. Positions are CONTENT coordinates (scrollTop/Left
        are added in), so the popover scrolls with the text it belongs to.
        whitespace-normal resets the container's pre-wrap, as for the pill.
      -->
      <div
        v-if="focusIndex !== null"
        ref="actionsEl"
        class="absolute z-20 w-max max-w-[min(34rem,calc(100%_-_1rem))] whitespace-normal"
        :style="actionsStyle"
      >
        <slot name="actions" />
      </div>

      <!-- Floating "Schwärzen" pill near the end of a valid text selection.
           Above the actions popover: it belongs to the gesture in progress. -->
      <div
        v-if="pendingSelection"
        ref="popoverEl"
        class="absolute z-30 whitespace-normal"
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
import {
  buildHighlightSegments,
  type HighlightSegment,
  type MatchRange,
} from '@/utils/textSegments'
import { getPillClass } from '@/utils/statusStyles'
import { overrideKey, useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { extractApiErrorMessage } from '@/utils/errors'
import {
  ENTITY_STATUSES,
  ENTITY_DOT_CLASSES,
  WARNING_DOT_CLASS,
  SEARCH_MATCH_ACTIVE_CLASS,
  SEARCH_MATCH_CLASS,
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
  /** Indices of ALL selected entities (document order). */
  selectedIndices: number[]
  /** The last-touched entity — scrolled into view, never color alone. */
  focusIndex: number | null
  /** Panel-search hits over the source text (empty when no search is open). */
  matches?: MatchRange[]
  /** Index of the hit the reviewer is currently on, or null. */
  activeMatchIndex?: number | null
}

const props = withDefaults(defineProps<Props>(), {
  matches: () => [],
  activeMatchIndex: null,
})

const emit = defineEmits<{
  /** Plain click: this entity becomes the whole selection. */
  (e: 'select', index: number): void
  /** Ctrl/Cmd-click: add/remove this entity. */
  (e: 'toggle', index: number): void
  /** Shift-click: select the range from the anchor to this entity. */
  (e: 'range', index: number): void
  /** Escape inside the panel: drop the selection. */
  (e: 'clear'): void
}>()

const { t } = useI18n()
const session = useSessionStore()
const toast = useToast()

const segments = computed(() =>
  buildHighlightSegments(props.sourceText, props.entities, props.warnings, props.matches),
)

/**
 * One entity can render as several segments — a validation warning or a search
 * hit runs through it. Rounding and padding only the OUTER edges keeps those
 * pieces reading as the one mark they are, instead of as adjacent finds.
 */
function markEdgeClass(index: number): string {
  const all = segments.value
  const entityIndex = all[index]?.entityIndex ?? null
  const classes: string[] = []
  if (all[index - 1]?.entityIndex !== entityIndex) classes.push('rounded-l-md pl-1')
  if (all[index + 1]?.entityIndex !== entityIndex) classes.push('rounded-r-md pr-1')
  return classes.join(' ')
}

/** Search-hit styling, layered on top of whatever mark the segment sits in. */
function matchClass(segment: HighlightSegment): string {
  if (segment.matchIndex === null) return ''
  return segment.matchIndex === props.activeMatchIndex
    ? `${SEARCH_MATCH_CLASS} ${SEARCH_MATCH_ACTIVE_CLASS}`
    : SEARCH_MATCH_CLASS
}

/**
 * Bring the active hit on screen. A hit can be split across several segments
 * (an entity or warning boundary runs through it) — the first one is where the
 * match starts, so that is what to scroll to.
 */
watch(
  () => [props.activeMatchIndex, props.matches] as const,
  async () => {
    if (props.activeMatchIndex === null) return
    await nextTick()
    textContainer.value
      ?.querySelector(`[data-match-index="${props.activeMatchIndex}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  },
)

function entityAt(index: number): AnonymizedEntity {
  // Segments are derived from props.entities, so the index is always valid.
  return props.entities[index]!
}

const selectedSet = computed(() => new Set(props.selectedIndices))

function isSelected(index: number | null): boolean {
  return index !== null && selectedSet.value.has(index)
}

/**
 * Modifier-aware mark activation. Ctrl/Cmd toggles one entity, Shift takes the
 * range from the anchor — the gestures every file list uses. Enter/Space on the
 * focused mark goes through the same path and carries the same modifier flags,
 * so the whole selection model works without a mouse.
 */
function handleMarkClick(index: number, event: MouseEvent | KeyboardEvent): void {
  if (event.shiftKey) {
    // A shift-drag over text also ends in a click; clear the incidental
    // native selection so the "Schwärzen" popover does not fight the range.
    window.getSelection()?.removeAllRanges()
    hidePopover()
    emit('range', index)
    return
  }
  if (event.ctrlKey || event.metaKey) {
    emit('toggle', index)
    return
  }
  emit('select', index)
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

/** Native tooltip: "Person · [PERSON_1] · geändert · ausgewählt". */
function markTitle(index: number): string {
  const entity = entityAt(index)
  const parts = [markTypeLabel(index), entity.replacement ?? entityStatusLabel(entity.status)]
  if (isOverridden(index)) parts.push(t('detail.changed_short'))
  if (isSelected(index)) parts.push(t('highlights.selected_short'))
  return parts.join(' · ')
}

/**
 * Accessible name of a mark — neither status nor selection is ever conveyed by
 * color alone (`aria-pressed` carries the selection too, for screen readers
 * that announce it).
 */
function markAriaLabel(index: number): string {
  const params = {
    type: markTypeLabel(index),
    status: entityStatusLabel(entityAt(index).status),
  }
  const label = isOverridden(index)
    ? t('highlights.mark_label_overridden', params)
    : t('highlights.mark_label', params)
  return isSelected(index) ? `${label}, ${t('highlights.selected_short')}` : label
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

// ---------------------------------------------------------------------------
// Anchoring the actions popover to the focused mark.
//
// The popover is positioned in CONTENT coordinates inside the scroll container
// (like the manual-redaction pill), so it travels with the text instead of
// needing a reposition on every scroll event.
// ---------------------------------------------------------------------------

/** Gap between the mark and the popover, and the inset kept from the edges. */
const ANCHOR_GAP = 6
const ANCHOR_INSET = 8

const actionsEl = ref<HTMLElement | null>(null)
const actionsAnchor = ref<{ top: number; left: number } | null>(null)

const actionsStyle = computed(() => ({
  top: `${actionsAnchor.value?.top ?? 0}px`,
  left: `${actionsAnchor.value?.left ?? 0}px`,
  // Hidden rather than absent until measured: the popover has to be in the DOM
  // to have a width to clamp against, but must not flash at the wrong place.
  visibility: actionsAnchor.value === null ? ('hidden' as const) : ('visible' as const),
}))

/**
 * Place the popover under the focused mark — or above it when the mark sits
 * near the bottom of the panel and the popover would hang off the end.
 */
function positionActions(): void {
  const container = textContainer.value
  const panel = actionsEl.value
  const index = props.focusIndex
  if (!container || !panel || index === null) {
    actionsAnchor.value = null
    return
  }
  // An entity can be split across several segments (an overlapping warning);
  // the last one is where the label chip sits, so anchor there.
  const marks = container.querySelectorAll<HTMLElement>(`[data-entity-index="${index}"]`)
  const mark = marks[marks.length - 1]
  if (!mark) {
    actionsAnchor.value = null
    return
  }

  const containerRect = container.getBoundingClientRect()
  const markRect = mark.getBoundingClientRect()
  const height = panel.offsetHeight
  const width = panel.offsetWidth

  const below = markRect.bottom - containerRect.top + container.scrollTop + ANCHOR_GAP
  const above = markRect.top - containerRect.top + container.scrollTop - height - ANCHOR_GAP
  // Flip up only when there is genuinely room up there — never off the top.
  const overflowsBelow = markRect.bottom + ANCHOR_GAP + height > containerRect.bottom
  const top = overflowsBelow && above >= container.scrollTop ? above : below

  const left = Math.max(
    ANCHOR_INSET,
    Math.min(
      markRect.left - containerRect.left + container.scrollLeft,
      container.clientWidth - width - ANCHOR_INSET,
    ),
  )
  actionsAnchor.value = { top, left }
}

/**
 * Bring the focused mark on screen (the selection may come from outside the
 * text — the entity summary, "alle Vorkommen", a warning), then place the
 * popover and make sure it is on screen too.
 */
async function revealSelection(scrollToMark: boolean): Promise<void> {
  await nextTick()
  const index = props.focusIndex
  if (index === null) {
    actionsAnchor.value = null
    return
  }
  if (scrollToMark) {
    textContainer.value
      ?.querySelector(`[data-entity-index="${index}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }
  positionActions()
  // A second tick: the popover's own size settles only once it has rendered
  // with the new content (different buttons, longer preview line).
  await nextTick()
  positionActions()
  if (scrollToMark) actionsEl.value?.scrollIntoView({ block: 'nearest' })
}

watch(
  () => props.focusIndex,
  () => void revealSelection(true),
)

// The popover's contents change size when the selection grows or a re-run
// relabels the marks; both leave the focus where it was, so no scrolling.
watch([() => props.selectedIndices.length, () => props.entities], () => void revealSelection(false))

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
  // Shift belongs to range selection in this panel: a shift-click extends the
  // NATIVE text selection as a side effect, which must not be mistaken for a
  // manual-redaction drag. Plain dragging is unaffected.
  if (event.shiftKey) {
    hidePopover()
    return
  }

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
  if (event.key !== 'Escape') return
  if (pendingSelection.value !== null) {
    hidePopover()
    return
  }
  // Escape drops the selection, but only while the reviewer is actually inside
  // the source review — it must not reach across the app from another panel.
  const active = document.activeElement
  if (active instanceof Node && textContainer.value?.contains(active)) emit('clear')
}

/** Re-anchor when the panel is resized (window, panel switcher, wrapping). */
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  // Document-level mouseup so selections released OUTSIDE the container (or
  // clicks elsewhere) are handled too; boundaries are validated per event.
  document.addEventListener('mouseup', handleSelectionMouseUp)
  document.addEventListener('mousedown', handleDocumentMouseDown)
  document.addEventListener('keydown', handleKeydown)
  if (textContainer.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => positionActions())
    resizeObserver.observe(textContainer.value)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mouseup', handleSelectionMouseUp)
  document.removeEventListener('mousedown', handleDocumentMouseDown)
  document.removeEventListener('keydown', handleKeydown)
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>
