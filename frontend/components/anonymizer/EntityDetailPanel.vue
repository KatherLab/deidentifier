<template>
  <!-- Compact footer bar inside the Quellprüfung card for the selected entity. -->
  <aside
    class="shrink-0 border-t border-default bg-surface-muted px-4 py-3"
    aria-label="Details zur ausgewählten Entität"
  >
    <div class="flex items-start gap-2">
      <div class="min-w-0 flex-1 space-y-2">
        <!-- Facts row: text, type, status, replacement, provenance. -->
        <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <span
            class="max-w-60 truncate font-mono text-sm font-medium text-content"
            :title="entity.text"
            >{{ entity.text }}</span
          >
          <StatusBadge :label="entityTypeLabel(entity.entity_type)" color="blue" />
          <StatusBadge
            :label="entityStatusLabel(entity.status)"
            :color="entityStatusPillColor(entity.status)"
          />
          <StatusBadge v-if="isOverridden" label="Geändert" color="purple" />
          <span
            v-if="entity.replacement !== null"
            class="font-mono text-xs text-content-muted"
            :title="`Ersetzt durch ${entity.replacement}`"
            >→ {{ entity.replacement }}</span
          >
          <span class="text-xs text-content-subtle">
            {{ transformationLabel(entity.transformation) }} · {{ entity.detector }} ·
            {{ confidenceLabel }} · Zeichen {{ entity.start }}–{{ entity.end }}
          </span>
        </div>

        <!-- Actions row. -->
        <div class="flex flex-wrap items-center gap-2">
          <BaseButton
            v-if="entity.status !== 'PRESERVED'"
            size="sm"
            variant="secondary"
            :disabled="rerunning"
            @click="setTransformation('PRESERVE')"
          >
            Beibehalten
          </BaseButton>
          <BaseButton
            v-else
            size="sm"
            variant="secondary"
            :disabled="rerunning"
            @click="setTransformation('TYPE_MASK')"
          >
            Schwärzen
          </BaseButton>
          <label :for="typeSelectId" class="sr-only">Entitätstyp</label>
          <select
            :id="typeSelectId"
            v-model="selectedType"
            :disabled="rerunning"
            class="rounded-card border border-strong bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            <option v-for="(label, type) in ENTITY_TYPE_LABELS" :key="type" :value="type">
              {{ label }}
            </option>
          </select>
          <BaseButton
            size="sm"
            variant="secondary"
            :disabled="rerunning || selectedType === entity.entity_type"
            @click="applyType"
          >
            Typ ändern
          </BaseButton>
          <BaseButton
            v-if="hasOverride"
            size="sm"
            variant="ghost"
            :disabled="rerunning"
            @click="resetOverride"
          >
            Zurücksetzen
          </BaseButton>
          <span
            v-if="rerunning"
            class="inline-flex items-center gap-1.5 text-xs text-content-subtle"
            aria-live="polite"
          >
            <LoadingSpinner size="small" color="gray" inline label="" />
            Wird neu berechnet …
          </span>
        </div>
      </div>
      <BaseButton variant="icon" tone="gray" aria-label="Details schließen" @click="emit('close')">
        <X class="h-4 w-4" aria-hidden="true" />
      </BaseButton>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { X } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { extractApiErrorMessage } from '@/utils/errors'
import {
  ENTITY_TYPE_LABELS,
  entityStatusLabel,
  entityStatusPillColor,
  entityTypeLabel,
  transformationLabel,
} from '@/utils/entityLabels'
import type { AnonymizedEntity, EntityType, TransformationType } from '@/types/anonymizer'

interface Props {
  entity: AnonymizedEntity
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const session = useSessionStore()
const toast = useToast()

const typeSelectId = 'entity-type-select'

const confidenceLabel = computed(() => `${Math.round(props.entity.confidence * 100)} %`)
const rerunning = computed(() => session.rerunning)
const hasOverride = computed(() => session.overrideFor(props.entity) !== undefined)
const isOverridden = computed(() => props.entity.metadata?.overridden === true || hasOverride.value)

// The type dropdown follows the currently selected entity.
const selectedType = ref<EntityType>(props.entity.entity_type)
watch(
  () => props.entity,
  (entity) => {
    selectedType.value = entity.entity_type
  },
)

async function setTransformation(transformation: TransformationType) {
  try {
    await session.applyEntityOverride(props.entity, { transformation })
  } catch (err) {
    toast.error(extractApiErrorMessage(err))
  }
}

async function applyType() {
  try {
    await session.applyEntityOverride(props.entity, { entity_type: selectedType.value })
  } catch (err) {
    toast.error(extractApiErrorMessage(err))
  }
}

async function resetOverride() {
  try {
    await session.resetEntityOverride(props.entity)
  } catch (err) {
    toast.error(extractApiErrorMessage(err))
  }
}
</script>
