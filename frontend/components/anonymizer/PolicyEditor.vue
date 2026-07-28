<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="text-sm text-content-muted">
        Legt fest, wie erkannte Entitäten standardmäßig behandelt werden. Einzelne Fundstellen
        lassen sich später in der Quellprüfung anpassen.
      </p>
      <BaseButton
        size="sm"
        variant="ghost"
        :disabled="!session.policyCustomized"
        @click="session.resetPolicy()"
      >
        Zurücksetzen
      </BaseButton>
    </div>

    <div class="grid gap-x-8 gap-y-2 sm:grid-cols-2">
      <div
        v-for="entityType in entityTypes"
        :key="entityType"
        class="flex items-center justify-between gap-3"
      >
        <label
          :for="`policy-${entityType}`"
          class="inline-flex items-center gap-1.5 text-sm text-content"
        >
          {{ ENTITY_TYPE_LABELS[entityType] }}
          <span
            v-if="isCustomized(entityType)"
            class="h-1.5 w-1.5 rounded-full bg-purple-500 dark:bg-purple-400"
            title="Vom Standard abweichend"
            aria-hidden="true"
          ></span>
          <span v-if="isCustomized(entityType)" class="sr-only">(vom Standard abweichend)</span>
        </label>
        <select
          :id="`policy-${entityType}`"
          class="w-52 rounded-card border border-strong bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :value="session.policy[entityType]"
          @change="onChange(entityType, $event)"
        >
          <option
            v-for="option in POLICY_OPTIONS[entityType]"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </div>
    </div>

    <p class="rounded-card px-3 py-2 text-sm" :class="getBannerClass('amber')">
      Beibehalten reduziert den Schutz — nur verwenden, wenn die Daten im Ergebnis benötigt werden.
    </p>
  </div>
</template>

<script setup lang="ts">
import BaseButton from '@/components/common/BaseButton.vue'
import { useSessionStore } from '@/stores/session'
import { getBannerClass } from '@/utils/statusStyles'
import { ENTITY_TYPE_LABELS } from '@/utils/entityLabels'
import { DEFAULT_POLICY, POLICY_OPTIONS } from '@/utils/policy'
import type { EntityType, TransformationType } from '@/types/anonymizer'

const session = useSessionStore()

/** Row order follows the German label map (all 12 entity types). */
const entityTypes = Object.keys(ENTITY_TYPE_LABELS) as EntityType[]

function isCustomized(type: EntityType): boolean {
  return session.policy[type] !== DEFAULT_POLICY[type]
}

function onChange(type: EntityType, event: Event) {
  const value = (event.target as HTMLSelectElement).value as TransformationType
  session.setPolicyTransformation(type, value)
}
</script>
