<template>
  <!--
    Actions for SEVERAL selected entities — the multi-entity counterpart of
    EntityDetailPanel, floated next to the marks by EntityHighlights. Every
    action here costs exactly one re-run: the backend takes overrides as a list.
  -->
  <aside
    class="rounded-card border border-strong bg-surface px-3 py-2.5 shadow-lg"
    :aria-label="t('selection.panel_label')"
  >
    <div class="flex items-start gap-2">
      <div class="min-w-0 flex-1 space-y-2">
        <!-- What is selected. The texts are spelled out on purpose: a bulk
             release must never be a blind click on a number. -->
        <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <StatusBadge :label="countLabel" color="purple" />
          <span class="min-w-0 truncate font-mono text-sm text-content-muted" :title="fullPreview">
            {{ preview }}
          </span>
        </div>

        <!-- Actions. Counts are on the labels so the reviewer sees the size of
             the edit before making it, not after. -->
        <div class="flex flex-wrap items-center gap-2">
          <BaseButton
            v-if="redactableCount > 0"
            size="sm"
            variant="secondary"
            :disabled="rerunning"
            @click="run('redact')"
          >
            {{ t('selection.redact', { count: redactableCount }, redactableCount) }}
          </BaseButton>
          <BaseButton
            v-if="preservableCount > 0"
            size="sm"
            variant="secondary"
            :disabled="rerunning"
            @click="run('preserve')"
          >
            {{ t('selection.preserve', { count: preservableCount }, preservableCount) }}
          </BaseButton>
          <template v-if="typeChangeableCount > 0">
            <label :for="typeSelectId" class="sr-only">{{ t('selection.change_type') }}</label>
            <select
              :id="typeSelectId"
              v-model="selectedType"
              :disabled="rerunning"
              class="rounded-card border border-strong bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              @change="applyType"
            >
              <option value="">{{ t('selection.change_type') }}</option>
              <option v-for="type in ENTITY_TYPES" :key="type" :value="type">
                {{ entityTypeLabel(type) }}
              </option>
            </select>
          </template>
          <BaseButton
            v-if="overriddenCount > 0"
            size="sm"
            variant="ghost"
            :disabled="rerunning"
            @click="run('reset')"
          >
            {{ t('selection.reset', { count: overriddenCount }, overriddenCount) }}
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
      <BaseButton
        variant="icon"
        tone="gray"
        :aria-label="t('selection.clear')"
        @click="session.clearSelection()"
      >
        <X class="h-4 w-4" aria-hidden="true" />
      </BaseButton>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useSessionStore, type SelectionAction } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { extractApiErrorMessage } from '@/utils/errors'
import { ENTITY_TYPES, entityTypeLabel } from '@/utils/entityLabels'
import type { AnonymizedEntity, EntityType } from '@/types/anonymizer'

/** How many of the selected texts the preview line spells out. */
const PREVIEW_LIMIT = 4

const { t } = useI18n()
const session = useSessionStore()
const toast = useToast()

const typeSelectId = 'entity-selection-type-select'
const selectedType = ref<EntityType | ''>('')

const entities = computed<AnonymizedEntity[]>(() => session.selectedEntities)
const rerunning = computed(() => session.rerunning)

const countLabel = computed(() =>
  t('selection.count', { count: entities.value.length }, entities.value.length),
)

function isManual(entity: AnonymizedEntity): boolean {
  return entity.metadata?.user_manual === true
}

/** Detected entities currently preserved — the ones "Schwärzen" would act on. */
const redactableCount = computed(
  () =>
    entities.value.filter((entity) => !isManual(entity) && entity.status === 'PRESERVED').length,
)

/**
 * What "Beibehalten" would act on: detected entities that are still redacted,
 * plus manual spans (releasing one drops the override that created it).
 */
const preservableCount = computed(
  () => entities.value.filter((entity) => isManual(entity) || entity.status !== 'PRESERVED').length,
)

/** Manual spans have no detected type to change. */
const typeChangeableCount = computed(
  () => entities.value.filter((entity) => !isManual(entity)).length,
)

/** Selected entities carrying a pending override — what "Zurücksetzen" clears. */
const overriddenCount = computed(
  () => entities.value.filter((entity) => session.overrideFor(entity) !== undefined).length,
)

const previewTexts = computed(() => entities.value.map((entity) => entity.text))
const fullPreview = computed(() => previewTexts.value.join(' · '))
const preview = computed(() => {
  const texts = previewTexts.value
  const shown = texts.slice(0, PREVIEW_LIMIT).join(' · ')
  return texts.length > PREVIEW_LIMIT
    ? `${shown} ${t('selection.preview_more', { count: texts.length - PREVIEW_LIMIT })}`
    : shown
})

async function run(action: SelectionAction): Promise<void> {
  try {
    const changed = await session.applySelectionAction(action)
    if (changed === 0) return
    // Releasing several finds at once is the one direction that can put an
    // identifier back into the output — say what happened, out loud.
    if (action === 'preserve')
      toast.info(t('toast.selection_preserved', { count: changed }, changed))
  } catch (err) {
    toast.error(extractApiErrorMessage(err))
  }
}

async function applyType(): Promise<void> {
  const type = selectedType.value
  selectedType.value = '' // the select is an action, not a state
  if (type === '') return
  try {
    await session.applySelectionType(type)
  } catch (err) {
    toast.error(extractApiErrorMessage(err))
  }
}
</script>
