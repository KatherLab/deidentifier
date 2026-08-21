<template>
  <!-- Details and actions for the ONE selected entity, floated next to its
       mark by EntityHighlights. -->
  <aside
    class="rounded-card border border-strong bg-surface px-3 py-2.5 shadow-lg"
    :aria-label="t('detail.panel_label')"
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
          <StatusBadge :label="typeBadgeLabel" color="blue" />
          <StatusBadge
            :label="entityStatusLabel(entity.status)"
            :color="entityStatusPillColor(entity.status)"
          />
          <StatusBadge
            v-if="isOverridden && !isUserManual"
            :label="t('detail.changed')"
            color="purple"
          />
          <span
            v-if="entity.replacement !== null"
            class="font-mono text-xs text-content-muted"
            :title="t('detail.replaced_by', { replacement: entity.replacement })"
            >→ {{ entity.replacement }}</span
          >
          <!-- Diagnostics (transformation, detector, confidence, offsets):
               expert-only. -->
          <span v-if="settings.expertMode" class="text-xs text-content-subtle">
            {{ transformationLabel(entity.transformation) }} · {{ entity.detector }} ·
            {{ confidenceLabel }} ·
            {{ t('detail.offsets', { start: entity.start, end: entity.end }) }}
          </span>
        </div>

        <!-- Actions row. Manual redactions only offer "Zurücksetzen" — the
             transformation toggle and type change don't apply to them. -->
        <div class="flex flex-wrap items-center gap-2">
          <template v-if="!isUserManual">
            <BaseButton
              v-if="entity.status !== 'PRESERVED'"
              size="sm"
              variant="secondary"
              :disabled="rerunning"
              @click="setTransformation('PRESERVE')"
            >
              {{ t('detail.preserve') }}
            </BaseButton>
            <BaseButton
              v-else
              size="sm"
              variant="secondary"
              :disabled="rerunning"
              @click="setTransformation('TYPE_MASK')"
            >
              {{ t('detail.redact') }}
            </BaseButton>
            <label :for="typeSelectId" class="sr-only">{{ t('detail.change_type') }}</label>
            <!-- Changing the type applies immediately (re-run with override). -->
            <select
              :id="typeSelectId"
              v-model="selectedType"
              :disabled="rerunning"
              class="rounded-card border border-strong bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              @change="applyType"
            >
              <option v-for="type in ENTITY_TYPES" :key="type" :value="type">
                {{ entityTypeLabel(type) }}
              </option>
            </select>
          </template>
          <BaseButton
            v-if="hasOverride"
            size="sm"
            variant="ghost"
            :disabled="rerunning"
            @click="resetOverride"
          >
            {{ t('common.reset') }}
          </BaseButton>
          <!-- The discoverable way into a multi-selection: one click turns
               "this name" into "all 14 of it", then the selection bar takes
               over. Only offered when there is more than one occurrence. -->
          <BaseButton
            v-if="occurrenceCount > 1"
            size="sm"
            variant="ghost"
            :disabled="rerunning"
            @click="session.selectMatchingEntities(entity)"
          >
            {{ t('detail.select_all_occurrences', { count: occurrenceCount }, occurrenceCount) }}
          </BaseButton>
          <!-- The final check, in one click: does this text still occur in the
               output? Opens the result panel's search on exactly this term. -->
          <BaseButton
            size="sm"
            variant="ghost"
            :title="t('detail.search_in_result_title')"
            @click="emit('search', entity.text)"
          >
            <Search class="h-3.5 w-3.5" aria-hidden="true" />
            {{ t('detail.search_in_result') }}
          </BaseButton>
          <span
            v-if="rerunning"
            class="inline-flex items-center gap-1.5 text-xs text-content-subtle"
            aria-live="polite"
          >
            <LoadingSpinner size="small" color="gray" inline label="" />
            {{ t('result.rerunning') }}
          </span>
        </div>
      </div>
      <BaseButton variant="icon" tone="gray" :aria-label="t('detail.close')" @click="emit('close')">
        <X class="h-4 w-4" aria-hidden="true" />
      </BaseButton>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search, X } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { extractApiErrorMessage } from '@/utils/errors'
import {
  ENTITY_TYPES,
  entityStatusLabel,
  entityStatusPillColor,
  entityTypeLabel,
  transformationLabel,
} from '@/utils/entityLabels'
import { formatPercent } from '@/utils/format'
import type { AnonymizedEntity, EntityType, TransformationType } from '@/types/anonymizer'

interface Props {
  entity: AnonymizedEntity
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
  /** Look this text up in the result panel's search. */
  (e: 'search', term: string): void
}>()

const { t } = useI18n()
const session = useSessionStore()
const settings = useSettingsStore()
const toast = useToast()

const typeSelectId = 'entity-type-select'

const confidenceLabel = computed(() => formatPercent(props.entity.confidence * 100))
/** How often this exact text was found — drives "Alle N Vorkommen wählen". */
const occurrenceCount = computed(() => session.countMatchingEntities(props.entity))
const rerunning = computed(() => session.rerunning)
const hasOverride = computed(() => session.overrideFor(props.entity) !== undefined)
const isOverridden = computed(() => props.entity.metadata?.overridden === true || hasOverride.value)

/** Manually redacted selection (backend-created span, detector `user_manual`). */
const isUserManual = computed(() => props.entity.metadata?.user_manual === true)
const typeBadgeLabel = computed(() =>
  isUserManual.value ? t('entity.manual_badge') : entityTypeLabel(props.entity.entity_type),
)

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
  if (selectedType.value === props.entity.entity_type) return
  try {
    await session.applyEntityOverride(props.entity, { entity_type: selectedType.value })
  } catch (err) {
    // The override was rolled back — the dropdown must follow.
    selectedType.value = props.entity.entity_type
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
