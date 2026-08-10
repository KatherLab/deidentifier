<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-start justify-between gap-2">
      <p class="max-w-prose text-sm text-content-muted">{{ t('policy.intro') }}</p>
      <BaseButton
        size="sm"
        variant="ghost"
        :disabled="!session.advancedCustomized"
        @click="session.resetAdvancedSettings()"
      >
        {{ t('common.reset') }}
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
              {{ entityTypeLabel(entityType) }}
              <span
                v-if="isCustomized(entityType)"
                class="h-1.5 w-1.5 rounded-full bg-purple-500 dark:bg-purple-400"
                :title="t('policy.customized_title')"
                aria-hidden="true"
              ></span>
              <span v-if="isCustomized(entityType)" class="sr-only">
                {{ t('policy.customized_sr') }}
              </span>
            </label>
            <p class="text-xs text-content-subtle">
              {{ entityTypeDescription(entityType) }}
            </p>
          </div>
          <select
            :id="`policy-${entityType}`"
            class="w-44 shrink-0 rounded-card border border-strong bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :value="session.policy[entityType]"
            @change="onChange(entityType, $event)"
          >
            <option v-for="option in POLICY_OPTIONS[entityType]" :key="option" :value="option">
              {{ policyOptionLabel(option, session.outputLanguage) }}
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
          {{ transformationHint(session.policy[entityType], entityType, session.outputLanguage) }}
        </p>
      </div>
    </div>

    <!-- Eigene Regeln: user-defined terms + free-text LLM instruction. -->
    <section class="space-y-4 border-t border-default pt-4">
      <h3 class="text-sm font-semibold text-content">{{ t('policy.custom_rules.title') }}</h3>

      <div>
        <label for="redact-terms" class="text-sm font-medium text-content">
          {{ t('policy.custom_rules.redact_label') }}
        </label>
        <ChipsInput
          v-model="session.redactTerms"
          input-id="redact-terms"
          class="mt-1"
          :placeholder="t('policy.custom_rules.chips_placeholder')"
        />
        <p class="mt-1 text-xs text-content-subtle">
          {{ t('policy.custom_rules.redact_hint') }}
        </p>
      </div>

      <div class="rounded-card bg-amber-50 p-3 dark:bg-amber-900/20">
        <label for="preserve-terms" class="text-sm font-medium text-content">
          {{ t('policy.custom_rules.preserve_label') }}
        </label>
        <ChipsInput
          v-model="session.preserveTerms"
          input-id="preserve-terms"
          tone="amber"
          class="mt-1"
          :placeholder="t('policy.custom_rules.chips_placeholder')"
        />
        <p class="mt-1 text-xs text-amber-700 dark:text-amber-300">
          {{ t('policy.custom_rules.preserve_hint') }}
        </p>
      </div>

      <div>
        <label for="custom-instruction" class="text-sm font-medium text-content">
          {{ t('policy.custom_rules.instruction_label') }}
        </label>
        <textarea
          id="custom-instruction"
          v-model="session.customInstruction"
          rows="3"
          :maxlength="INSTRUCTION_MAX_LENGTH"
          :placeholder="t('policy.custom_rules.instruction_placeholder')"
          class="mt-1 w-full rounded-card border border-strong bg-surface p-3 text-sm text-content placeholder:text-content-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        ></textarea>
        <div class="flex items-start justify-between gap-3">
          <p class="text-xs text-content-subtle">
            {{ t('policy.custom_rules.instruction_hint') }}
          </p>
          <span class="shrink-0 text-xs tabular-nums text-content-subtle">
            {{ session.customInstruction.length }}/{{ INSTRUCTION_MAX_LENGTH }}
          </span>
        </div>
      </div>
    </section>

    <!-- Sprache des Ergebnisses: the placeholders written INTO the document.
         Captured at submit, so switching the interface language later never
         rewrites a finished document. -->
    <section class="space-y-3 border-t border-default pt-4">
      <h3 class="text-sm font-semibold text-content">{{ t('policy.output_language.title') }}</h3>
      <div class="flex flex-wrap items-center gap-3">
        <label for="output-language" class="text-sm text-content">
          {{ t('policy.output_language.label') }}
        </label>
        <select
          id="output-language"
          class="w-64 rounded-card border border-strong bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :value="session.outputLanguageOverride ?? ''"
          @change="onOutputLanguageChange($event)"
        >
          <option value="">
            {{ t('policy.output_language.follow_ui', { language: t(`language.${locale}`) }) }}
          </option>
          <option v-for="loc in supportedLocales" :key="loc" :value="loc">
            {{ t(`language.${loc}`) }}
          </option>
        </select>
      </div>
      <p class="text-xs text-content-subtle">
        {{
          t('policy.output_language.hint', {
            example: consistentTagExample(session.outputLanguage),
          })
        }}
      </p>
    </section>

    <!-- Texterkennung: force OCR (only when an OCR engine is configured). -->
    <section v-if="ocrEnabled" class="space-y-3 border-t border-default pt-4">
      <h3 class="text-sm font-semibold text-content">{{ t('policy.ocr.title') }}</h3>
      <!-- OCR model selection, only when the server configures several. -->
      <div v-if="ocrProfiles.length >= 2" class="space-y-1">
        <div class="flex flex-wrap items-center gap-3">
          <label for="ocr-profile" class="text-sm text-content">
            {{ t('policy.ocr.profile_label') }}
          </label>
          <select
            id="ocr-profile"
            class="w-64 rounded-card border border-strong bg-surface px-2 py-1 text-sm text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :value="session.ocrProfile ?? ''"
            @change="onOcrProfileChange($event)"
          >
            <option value="">
              {{ t('policy.ocr.profile_default', { name: defaultOcrProfileName }) }}
            </option>
            <option v-for="profile in ocrProfiles" :key="profile.name" :value="profile.name">
              {{ profile.name }} ({{ profile.model }})
            </option>
          </select>
        </div>
        <p class="text-xs text-content-subtle">{{ t('policy.ocr.profile_hint') }}</p>
      </div>
      <label class="flex items-start gap-3">
        <input
          type="checkbox"
          class="mt-0.5 h-4 w-4 shrink-0 rounded border-strong text-purple-600 focus:ring-ring"
          :checked="session.forceOcr"
          @change="onForceOcrChange($event)"
        />
        <span class="min-w-0">
          <span class="text-sm font-medium text-content">{{ t('policy.ocr.force_label') }}</span>
          <span class="mt-0.5 block text-xs text-content-subtle">
            {{ t('policy.ocr.force_hint') }}
          </span>
        </span>
      </label>
    </section>

    <p class="text-xs text-content-subtle">{{ t('policy.applies_next_run') }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseButton from '@/components/common/BaseButton.vue'
import ChipsInput from '@/components/common/ChipsInput.vue'
import { useSessionStore } from '@/stores/session'
import { loadLocaleMessages, useLocale } from '@/composables/useLocale'
import { ENTITY_TYPES, entityTypeDescription, entityTypeLabel } from '@/utils/entityLabels'
import { consistentTagExample } from '@/utils/placeholders'
import {
  DEFAULT_POLICY,
  POLICY_OPTIONS,
  policyOptionLabel,
  transformationHint,
} from '@/utils/policy'
import type { EntityType, OutputLanguage, TransformationType } from '@/types/anonymizer'

/** Mirrors the backend's limit for `custom_instruction`. */
const INSTRUCTION_MAX_LENGTH = 2000

const { t } = useI18n()
const { locale, supportedLocales } = useLocale()
const session = useSessionStore()

/** Row order follows the canonical entity-type order (all 12 types). */
const entityTypes = ENTITY_TYPES

// The rows preview the placeholders of the SELECTED output language, so every
// catalog must be in memory before the user picks one — otherwise the preview
// briefly shows the German tokens (vue-i18n's fallback) for a language whose
// catalog is still loading. Only paid once the user opens advanced settings.
onMounted(() => {
  for (const loc of supportedLocales) void loadLocaleMessages(loc)
})

/** Force-OCR only makes sense when the backend has an OCR engine configured. */
const ocrEnabled = computed(() => (session.status?.ocr_engine ?? 'none') !== 'none')

/** Selectable OCR profiles; the picker appears only when there is a choice. */
const ocrProfiles = computed(() => session.status?.ocr_profiles ?? [])
const defaultOcrProfileName = computed(
  () => ocrProfiles.value.find((profile) => profile.default)?.name ?? '',
)

/** "" = follow the interface language; otherwise pin that output language. */
function onOutputLanguageChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  session.setOutputLanguage(value === '' ? null : (value as OutputLanguage))
}

function onForceOcrChange(event: Event): void {
  session.forceOcr = (event.target as HTMLInputElement).checked
}

/** "" = the server's default profile; otherwise pin one for the next run. */
function onOcrProfileChange(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  session.ocrProfile = value === '' ? null : value
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
