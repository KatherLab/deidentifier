<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-start justify-between gap-2">
      <p class="max-w-prose text-sm text-content-muted">
        Hier legen Sie fest, wie erkannte Datenarten ersetzt werden und ergänzen eigene Regeln. Die
        Standardeinstellung schwärzt alles Erkannte.
      </p>
      <BaseButton
        size="sm"
        variant="ghost"
        :disabled="!session.advancedCustomized"
        @click="session.resetAdvancedSettings()"
      >
        Zurücksetzen
      </BaseButton>
    </div>

    <!-- Default-policy table: one row per entity type. -->
    <div class="grid gap-x-4 gap-y-1 sm:grid-cols-2">
      <div
        v-for="entityType in entityTypes"
        :key="entityType"
        class="rounded-card px-2 py-2"
        :class="isPreserved(entityType) ? 'bg-amber-50 dark:bg-amber-900/20' : ''"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
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
              <span v-if="isCustomized(entityType)" class="sr-only">
                (vom Standard abweichend)
              </span>
            </label>
            <p class="text-xs text-content-subtle">
              {{ ENTITY_TYPE_DESCRIPTIONS[entityType] }}
            </p>
          </div>
          <select
            :id="`policy-${entityType}`"
            class="w-44 shrink-0 rounded-card border border-strong bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
        <!-- Hint for the CURRENTLY selected transformation, with an example. -->
        <p
          class="mt-1 text-xs"
          :class="
            isPreserved(entityType) ? 'text-amber-700 dark:text-amber-300' : 'text-content-subtle'
          "
        >
          {{ TRANSFORMATION_HINTS[session.policy[entityType]] }}
        </p>
      </div>
    </div>

    <!-- Eigene Regeln: user-defined terms + free-text LLM instruction. -->
    <section class="space-y-4 border-t border-default pt-4">
      <h3 class="text-sm font-semibold text-content">Eigene Regeln</h3>

      <div>
        <label for="redact-terms" class="text-sm font-medium text-content">
          Zusätzlich schwärzen
        </label>
        <ChipsInput
          v-model="session.redactTerms"
          input-id="redact-terms"
          class="mt-1"
          placeholder="Begriff eingeben, mit Enter oder Komma hinzufügen"
        />
        <p class="mt-1 text-xs text-content-subtle">
          Diese Begriffe werden immer und überall geschwärzt – unabhängig von der KI-Erkennung
          (ganze Wörter, Groß-/Kleinschreibung egal). Beispiel: interne Stationsnamen.
        </p>
      </div>

      <div class="rounded-card bg-amber-50 p-3 dark:bg-amber-900/20">
        <label for="preserve-terms" class="text-sm font-medium text-content">Nie schwärzen</label>
        <ChipsInput
          v-model="session.preserveTerms"
          input-id="preserve-terms"
          tone="amber"
          class="mt-1"
          placeholder="Begriff eingeben, mit Enter oder Komma hinzufügen"
        />
        <p class="mt-1 text-xs text-amber-700 dark:text-amber-300">
          Erkannte Stellen mit genau diesem Wortlaut bleiben sichtbar. Vorsicht: reduziert den
          Schutz.
        </p>
      </div>

      <div>
        <label for="custom-instruction" class="text-sm font-medium text-content">
          Zusätzliche Anweisung an die KI-Erkennung
        </label>
        <textarea
          id="custom-instruction"
          v-model="session.customInstruction"
          rows="3"
          :maxlength="INSTRUCTION_MAX_LENGTH"
          placeholder="z. B.: Melde auch Zimmernummern und Studien-IDs (z. B. NCT-Nummern)."
          class="mt-1 w-full rounded-card border border-strong bg-surface p-3 text-sm text-content placeholder:text-content-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        ></textarea>
        <div class="flex items-start justify-between gap-3">
          <p class="text-xs text-content-subtle">
            Freitext, der der KI-Erkennung mitgegeben wird. Kann die Erkennung nur erweitern oder
            präzisieren – die Standarderkennung und alle deterministischen Prüfungen bleiben immer
            aktiv.
          </p>
          <span class="shrink-0 text-xs tabular-nums text-content-subtle">
            {{ session.customInstruction.length }}/{{ INSTRUCTION_MAX_LENGTH }}
          </span>
        </div>
      </div>
    </section>

    <!-- Texterkennung: force OCR (only when an OCR engine is configured). -->
    <section v-if="ocrEnabled" class="space-y-3 border-t border-default pt-4">
      <h3 class="text-sm font-semibold text-content">Texterkennung (OCR)</h3>
      <label class="flex items-start gap-3">
        <input
          type="checkbox"
          class="mt-0.5 h-4 w-4 shrink-0 rounded border-strong text-purple-600 focus:ring-ring"
          :checked="session.forceOcr"
          @change="onForceOcrChange($event)"
        />
        <span class="min-w-0">
          <span class="text-sm font-medium text-content">OCR erzwingen</span>
          <span class="mt-0.5 block text-xs text-content-subtle">
            Liest hochgeladene PDFs immer per Texterkennung neu ein, statt eine vorhandene Textebene
            zu verwenden. Sinnvoll für Scans mit fehlender oder fehlerhafter Textebene. Betrifft nur
            PDF-Uploads (nicht Text/DOCX) und macht die Verarbeitung langsamer.
          </span>
        </span>
      </label>
    </section>

    <p class="text-xs text-content-subtle">Änderungen gelten für den nächsten Durchlauf.</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import BaseButton from '@/components/common/BaseButton.vue'
import ChipsInput from '@/components/common/ChipsInput.vue'
import { useSessionStore } from '@/stores/session'
import { ENTITY_TYPE_DESCRIPTIONS, ENTITY_TYPE_LABELS } from '@/utils/entityLabels'
import { DEFAULT_POLICY, POLICY_OPTIONS, TRANSFORMATION_HINTS } from '@/utils/policy'
import type { EntityType, TransformationType } from '@/types/anonymizer'

/** Mirrors the backend's limit for `custom_instruction`. */
const INSTRUCTION_MAX_LENGTH = 2000

const session = useSessionStore()

/** Row order follows the German label map (all 12 entity types). */
const entityTypes = Object.keys(ENTITY_TYPE_LABELS) as EntityType[]

/** Force-OCR only makes sense when the backend has an OCR engine configured. */
const ocrEnabled = computed(() => (session.status?.ocr_engine ?? 'none') !== 'none')

function onForceOcrChange(event: Event): void {
  session.forceOcr = (event.target as HTMLInputElement).checked
}

function isCustomized(type: EntityType): boolean {
  return session.policy[type] !== DEFAULT_POLICY[type]
}

/** PRESERVE rows are tinted amber as a visual caution (reduced protection). */
function isPreserved(type: EntityType): boolean {
  return session.policy[type] === 'PRESERVE'
}

function onChange(type: EntityType, event: Event) {
  const value = (event.target as HTMLSelectElement).value as TransformationType
  session.setPolicyTransformation(type, value)
}
</script>
