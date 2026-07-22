<template>
  <section class="space-y-6">
    <!-- Header: validation status + actions -->
    <div class="flex flex-wrap items-center gap-3">
      <StatusBadge
        :label="validationStatusLabel(result.validation.status)"
        :color="validationStatusColor(result.validation.status)"
        class="text-sm"
      />
      <StatusBadge :label="sourceTypeLabel(result.source_type)" color="gray" />
      <span class="text-xs text-content-subtle">
        Verarbeitet in {{ Math.round(result.timing_ms.total) }} ms
      </span>
      <span
        v-if="session.rerunning"
        class="inline-flex items-center gap-1.5 text-xs text-content-subtle"
        aria-live="polite"
      >
        <LoadingSpinner size="small" color="gray" inline label="" />
        Wird neu berechnet …
      </span>
      <div class="ml-auto">
        <BaseButton variant="secondary" @click="session.reset()">Neues Dokument</BaseButton>
      </div>
    </div>

    <!-- View toggle: anonymized text | source review -->
    <div
      class="inline-flex rounded-card border border-default bg-surface-sunken p-1"
      role="tablist"
      aria-label="Ansicht wählen"
    >
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.id"
        class="rounded-card px-3 py-1.5 text-sm font-medium transition-colors"
        :class="
          activeTab === tab.id
            ? 'bg-surface text-content shadow-sm'
            : 'text-content-muted hover:text-content'
        "
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Anonymized text -->
    <div v-if="activeTab === 'anonymized'" class="space-y-3">
      <div class="flex flex-wrap gap-2">
        <BaseButton variant="secondary" @click="copyAnonymized">
          <Copy class="h-4 w-4" aria-hidden="true" />
          Kopieren
        </BaseButton>
        <BaseButton variant="secondary" @click="downloadAnonymized">
          <Download class="h-4 w-4" aria-hidden="true" />
          Als .txt herunterladen
        </BaseButton>
      </div>
      <!-- v-text: the panel is whitespace-pre-wrap, so template indentation must not leak in. -->
      <div
        class="rounded-card border border-default bg-surface p-4 text-sm leading-7 whitespace-pre-wrap break-words text-content"
        v-text="result.anonymized_text"
      ></div>
    </div>

    <!-- Source review -->
    <div v-else class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <EntityHighlights
        :source-text="result.source_text"
        :entities="result.entities"
        :warnings="result.validation.warnings"
        :selected-index="session.selectedEntityIndex"
        @select="session.selectEntity($event)"
      />
      <EntityDetailPanel
        v-if="session.selectedEntity"
        :entity="session.selectedEntity"
        class="lg:sticky lg:top-4 self-start"
        @close="session.selectEntity(null)"
      />
      <p v-else class="text-sm text-content-subtle lg:pt-4">
        Klicken Sie auf eine markierte Stelle, um Details zur erkannten Entität anzuzeigen.
      </p>
    </div>

    <!-- Entity counts by type -->
    <section v-if="session.entityCounts.length > 0" class="space-y-2">
      <h3 class="text-sm font-semibold text-content">Erkannte Entitäten</h3>
      <div class="flex flex-wrap gap-2">
        <StatusBadge
          v-for="item in session.entityCounts"
          :key="item.type"
          :label="`${entityTypeLabel(item.type)}: ${item.count}`"
          color="blue"
        />
      </div>
    </section>
    <p v-else class="text-sm text-content-subtle">Keine Entitäten erkannt.</p>

    <!-- Warnings -->
    <WarningsList
      :validation-warnings="result.validation.warnings"
      :general-warnings="result.warnings"
      @locate="showWarningInSource"
    />
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Copy, Download } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import EntityHighlights from '@/components/anonymizer/EntityHighlights.vue'
import EntityDetailPanel from '@/components/anonymizer/EntityDetailPanel.vue'
import WarningsList from '@/components/anonymizer/WarningsList.vue'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { useFileDownload } from '@/composables/useFileDownload'
import {
  entityTypeLabel,
  sourceTypeLabel,
  validationStatusColor,
  validationStatusLabel,
} from '@/utils/entityLabels'
import type { AnonymizeResponse } from '@/types/anonymizer'

interface Props {
  result: AnonymizeResponse
}

const props = defineProps<Props>()

const session = useSessionStore()
const toast = useToast()
const { downloadBlob } = useFileDownload()

type TabId = 'anonymized' | 'source'
const tabs: { id: TabId; label: string }[] = [
  { id: 'anonymized', label: 'Anonymisierter Text' },
  { id: 'source', label: 'Quellprüfung' },
]
const activeTab = ref<TabId>('anonymized')

async function copyAnonymized() {
  try {
    await navigator.clipboard.writeText(props.result.anonymized_text)
    toast.success('Anonymisierter Text in die Zwischenablage kopiert.')
  } catch {
    toast.error('Kopieren fehlgeschlagen. Bitte markieren und manuell kopieren.')
  }
}

function downloadAnonymized() {
  downloadBlob(props.result.anonymized_text, 'anonymisiert.txt', 'text/plain;charset=utf-8')
}

function showWarningInSource() {
  activeTab.value = 'source'
}
</script>
