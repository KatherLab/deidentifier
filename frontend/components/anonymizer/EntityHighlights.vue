<template>
  <div class="space-y-3">
    <!-- Legend: color + text label per entity status, never color alone. -->
    <div class="flex flex-wrap items-center gap-2 text-xs" aria-label="Legende">
      <span class="font-semibold text-content-subtle uppercase tracking-wide">Legende:</span>
      <span
        v-for="item in legend"
        :key="item.label"
        class="inline-flex items-center gap-1 rounded px-1.5 py-0.5"
        :class="item.highlightClass"
      >
        {{ item.label }}
      </span>
    </div>

    <!-- Source text with highlighted entity spans. -->
    <div
      class="rounded-card border border-default bg-surface p-4 text-sm leading-7 whitespace-pre-wrap break-words"
    >
      <template v-for="segment in segments" :key="segment.key">
        <button
          v-if="segment.entityIndex !== null"
          type="button"
          class="inline rounded-sm px-0.5 box-decoration-clone cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :class="[
            entityHighlightClass(entityAt(segment.entityIndex).status),
            segment.entityIndex === selectedIndex ? 'ring-2 ring-ring' : '',
          ]"
          :aria-label="`Entität: ${entityTypeLabel(entityAt(segment.entityIndex).entity_type)}, ${entityStatusLabel(entityAt(segment.entityIndex).status)}${isOverridden(segment.entityIndex) ? ', geändert' : ''}`"
          @click="emit('select', segment.entityIndex)"
        >
          <!--
            v-text keeps the segment text free of template whitespace — the
            container is whitespace-pre-wrap, so stray indentation would render.
          -->
          <span v-text="segment.text"></span>
          <span
            v-if="segment.showEntityLabel"
            class="ml-1 rounded px-1 align-middle text-[10px] font-semibold uppercase tracking-wide"
            :class="entityChipClass(entityAt(segment.entityIndex).status)"
            v-text="entityTypeLabel(entityAt(segment.entityIndex).entity_type)"
          ></span>
          <!-- User-overridden entity marker (metadata.overridden from the backend). -->
          <span
            v-if="segment.showEntityLabel && isOverridden(segment.entityIndex)"
            class="ml-1 rounded bg-purple-200 px-1 align-middle text-[10px] font-semibold uppercase tracking-wide text-purple-900 dark:bg-purple-800 dark:text-purple-100"
            >geändert</span
          >
        </button>
        <mark
          v-else-if="segment.warning"
          class="rounded-sm px-0.5 box-decoration-clone"
          :class="WARNING_HIGHLIGHT_CLASS"
        >
          <span v-text="segment.text"></span>
          <span
            class="ml-1 rounded bg-yellow-200 px-1 align-middle text-[10px] font-semibold uppercase tracking-wide text-yellow-900 dark:bg-yellow-800 dark:text-yellow-100"
            >Warnung</span
          >
        </mark>
        <span v-else v-text="segment.text"></span>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { buildHighlightSegments } from '@/utils/textSegments'
import {
  ENTITY_STATUS_LABELS,
  ENTITY_HIGHLIGHT_CLASSES,
  WARNING_HIGHLIGHT_CLASS,
  entityChipClass,
  entityHighlightClass,
  entityStatusLabel,
  entityTypeLabel,
} from '@/utils/entityLabels'
import type { AnonymizedEntity, EntityStatus, ValidationWarning } from '@/types/anonymizer'

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

const legend = computed(() => {
  const statuses = Object.keys(ENTITY_STATUS_LABELS) as EntityStatus[]
  return [
    ...statuses.map((status) => ({
      label: ENTITY_STATUS_LABELS[status],
      highlightClass: ENTITY_HIGHLIGHT_CLASSES[status],
    })),
    { label: 'Warnung', highlightClass: WARNING_HIGHLIGHT_CLASS },
  ]
})
</script>
