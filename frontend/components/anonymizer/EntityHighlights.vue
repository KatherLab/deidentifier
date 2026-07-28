<template>
  <div class="flex min-h-0 flex-col">
    <!-- Compact legend: colored dot + label per status, never color alone. -->
    <div
      class="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-default bg-surface-muted px-4 py-2 text-xs text-content-muted"
      aria-label="Legende"
    >
      <span v-for="item in legend" :key="item.label" class="inline-flex items-center gap-1.5">
        <span class="h-2 w-2 rounded-full" :class="item.dotClass" aria-hidden="true"></span>
        {{ item.label }}
      </span>
    </div>

    <!-- Source text with highlighted entity marks. -->
    <div
      class="min-h-0 flex-1 overflow-y-auto p-6 font-sans text-[15px] leading-relaxed whitespace-pre-wrap break-words text-content"
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
          :aria-label="`Entität: ${entityTypeLabel(entityAt(segment.entityIndex).entity_type)}, ${entityStatusLabel(entityAt(segment.entityIndex).status)}${isOverridden(segment.entityIndex) ? ', geändert' : ''}`"
          @click="emit('select', segment.entityIndex)"
        >
          <!--
            v-text keeps the segment text free of template whitespace — the
            container is whitespace-pre-wrap, so stray indentation would render.
          -->
          <span v-text="segment.text"></span>
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
          title="Warnung · möglicherweise nicht erkannte personenbezogene Daten"
        >
          <span v-text="segment.text"></span>
        </mark>
        <span v-else v-text="segment.text"></span>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { buildHighlightSegments } from '@/utils/textSegments'
import { getPillClass } from '@/utils/statusStyles'
import {
  ENTITY_STATUS_LABELS,
  ENTITY_DOT_CLASSES,
  WARNING_DOT_CLASS,
  WARNING_HIGHLIGHT_CLASS,
  entityHighlightClass,
  entityStatusLabel,
  entityStatusPillColor,
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

/** Native tooltip: "Person · [PERSON_1] · geändert". */
function markTitle(index: number): string {
  const entity = entityAt(index)
  const parts = [
    entityTypeLabel(entity.entity_type),
    entity.replacement ?? entityStatusLabel(entity.status),
  ]
  if (isOverridden(index)) parts.push('geändert')
  return parts.join(' · ')
}

/** Superscript badge on the selected entity: replacement (or type). */
function badgeText(index: number): string {
  const entity = entityAt(index)
  return entity.replacement ?? entityTypeLabel(entity.entity_type)
}

const legend = computed(() => {
  const statuses = Object.keys(ENTITY_STATUS_LABELS) as EntityStatus[]
  return [
    ...statuses.map((status) => ({
      label: ENTITY_STATUS_LABELS[status],
      dotClass: ENTITY_DOT_CLASSES[status],
    })),
    { label: 'Warnung', dotClass: WARNING_DOT_CLASS },
  ]
})
</script>
