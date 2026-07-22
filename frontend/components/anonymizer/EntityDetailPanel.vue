<template>
  <aside
    class="rounded-card border border-default bg-surface-muted p-4 space-y-3"
    aria-label="Details zur ausgewählten Entität"
  >
    <div class="flex items-start justify-between gap-2">
      <h3 class="text-sm font-semibold text-content">Entitäts-Details</h3>
      <BaseButton variant="icon" tone="gray" aria-label="Details schließen" @click="emit('close')">
        <X class="h-4 w-4" aria-hidden="true" />
      </BaseButton>
    </div>

    <dl class="space-y-3 text-sm">
      <div>
        <dt class="text-xs uppercase tracking-wide text-content-subtle">Erkannter Text</dt>
        <dd class="mt-0.5 font-mono text-content break-all">{{ entity.text }}</dd>
      </div>
      <div>
        <dt class="text-xs uppercase tracking-wide text-content-subtle">Typ</dt>
        <dd class="mt-0.5 flex flex-wrap items-center gap-1.5">
          <StatusBadge :label="entityTypeLabel(entity.entity_type)" color="blue" />
          <StatusBadge v-if="isOverridden" label="Geändert" color="purple" />
        </dd>
      </div>
      <div>
        <dt class="text-xs uppercase tracking-wide text-content-subtle">Status</dt>
        <dd class="mt-0.5">
          <StatusBadge
            :label="entityStatusLabel(entity.status)"
            :color="entityStatusPillColor(entity.status)"
          />
        </dd>
      </div>
      <div>
        <dt class="text-xs uppercase tracking-wide text-content-subtle">Transformation</dt>
        <dd class="mt-0.5 text-content">{{ transformationLabel(entity.transformation) }}</dd>
      </div>
      <div>
        <dt class="text-xs uppercase tracking-wide text-content-subtle">Ersetzt durch</dt>
        <dd class="mt-0.5 font-mono text-content break-all">
          <template v-if="entity.replacement !== null">{{ entity.replacement }}</template>
          <span v-else class="font-sans text-content-subtle">— (keine Ersetzung)</span>
        </dd>
      </div>
      <div>
        <dt class="text-xs uppercase tracking-wide text-content-subtle">Detektor</dt>
        <dd class="mt-0.5 text-content">{{ entity.detector }}</dd>
      </div>
      <div>
        <dt class="text-xs uppercase tracking-wide text-content-subtle">Konfidenz</dt>
        <dd class="mt-0.5 text-content">{{ confidenceLabel }}</dd>
      </div>
      <div>
        <dt class="text-xs uppercase tracking-wide text-content-subtle">Position</dt>
        <dd class="mt-0.5 text-content">Zeichen {{ entity.start }}–{{ entity.end }}</dd>
      </div>
    </dl>

    <!-- Override actions -->
    <div class="space-y-3 border-t border-default pt-3">
      <h4 class="text-xs uppercase tracking-wide text-content-subtle">Aktionen</h4>

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
        <BaseButton
          v-if="hasOverride"
          size="sm"
          variant="ghost"
          :disabled="rerunning"
          @click="resetOverride"
        >
          Zurücksetzen
        </BaseButton>
      </div>

      <div class="space-y-1.5">
        <label :for="typeSelectId" class="block text-xs text-content-subtle">Entitätstyp</label>
        <div class="flex items-center gap-2">
          <select
            :id="typeSelectId"
            v-model="selectedType"
            :disabled="rerunning"
            class="min-w-0 flex-1 rounded-card border border-strong bg-surface px-2 py-1.5 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
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
        </div>
      </div>

      <p
        v-if="rerunning"
        class="flex items-center gap-2 text-xs text-content-subtle"
        aria-live="polite"
      >
        <LoadingSpinner size="small" color="gray" inline label="" />
        Wird neu berechnet …
      </p>
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
