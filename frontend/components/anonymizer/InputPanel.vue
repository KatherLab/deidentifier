<template>
  <!-- Processing state: centered progress card (streamed from the backend). -->
  <section v-if="loading" class="flex justify-center py-10">
    <div
      class="w-full max-w-lg space-y-4 rounded-modal border border-default bg-surface p-8 text-center shadow-sm"
    >
      <FileText class="mx-auto h-10 w-10 text-content-subtle" aria-hidden="true" />
      <p class="text-sm font-medium text-content break-all">{{ processingName }}</p>

      <!-- Progress bar: determinate fill once events arrive, shimmer before. -->
      <div
        class="h-2.5 w-full overflow-hidden rounded-full bg-surface-sunken"
        role="progressbar"
        aria-label="Fortschritt der Anonymisierung"
        :aria-valuemin="0"
        :aria-valuemax="100"
        :aria-valuenow="roundedPercent ?? undefined"
        :aria-valuetext="stageLabel"
      >
        <div
          v-if="percent !== null"
          class="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
          :style="{ width: `${percent}%` }"
        ></div>
        <div v-else class="progress-shimmer h-full w-1/3 rounded-full bg-primary"></div>
      </div>

      <p class="text-sm text-content-muted" aria-live="polite">
        <span v-if="roundedPercent !== null" class="font-semibold text-content"
          >{{ roundedPercent }} %</span
        >
        {{ stageLabel }}
      </p>
    </div>
  </section>

  <section v-else class="space-y-6">
    <!-- Local-processing notice -->
    <p
      class="rounded-card px-4 py-3 text-sm bg-blue-50 border border-blue-200 text-blue-800 dark:bg-blue-900/20 dark:border-blue-800 dark:text-blue-300"
    >
      Dokumente werden lokal von dieser Installation verarbeitet. Das Ergebnis ist kein Nachweis
      rechtssicherer Anonymisierung.
    </p>

    <!-- Drag-and-drop zone -->
    <div
      class="rounded-modal border-2 border-dashed p-8 text-center transition-colors cursor-pointer"
      :class="
        dragActive
          ? 'border-primary bg-primary-soft'
          : 'border-strong bg-surface-muted hover:border-primary'
      "
      role="button"
      tabindex="0"
      aria-label="Datei auswählen oder hierher ziehen"
      @click="openFilePicker"
      @keydown.enter.prevent="openFilePicker"
      @keydown.space.prevent="openFilePicker"
      @dragover.prevent="dragActive = true"
      @dragleave.prevent="dragActive = false"
      @drop.prevent="onDrop"
    >
      <input
        ref="fileInput"
        type="file"
        accept=".txt,.pdf,.docx"
        class="hidden"
        @change="onFileChange"
      />
      <div class="flex flex-col items-center gap-2">
        <UploadCloud class="h-10 w-10 text-content-subtle" aria-hidden="true" />
        <template v-if="!selectedFile">
          <p class="text-sm font-medium text-content">
            Datei hierher ziehen oder klicken, um auszuwählen
          </p>
          <p class="text-xs text-content-subtle">PDF, DOCX oder TXT</p>
        </template>
        <template v-else>
          <p class="text-sm font-medium text-content break-all">
            {{ selectedFile.name }}
            <span class="text-content-subtle font-normal">({{ fileSizeLabel }})</span>
          </p>
          <BaseButton variant="link" tone="gray" @click.stop="clearFile">
            Datei entfernen
          </BaseButton>
        </template>
      </div>
    </div>

    <!-- Divider -->
    <div class="flex items-center gap-3" aria-hidden="true">
      <div class="h-px flex-1 bg-(--color-default-border)"></div>
      <span class="text-xs uppercase tracking-wide text-content-subtle">oder Text einfügen</span>
      <div class="h-px flex-1 bg-(--color-default-border)"></div>
    </div>

    <!-- Paste textarea -->
    <div>
      <label for="paste-text" class="sr-only">Text einfügen</label>
      <textarea
        id="paste-text"
        v-model="pastedText"
        rows="10"
        :disabled="selectedFile !== null || loading"
        placeholder="Text hier einfügen …"
        class="w-full rounded-card border border-strong bg-surface p-3 text-sm text-content placeholder:text-content-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      ></textarea>
      <p v-if="selectedFile" class="mt-1 text-xs text-content-subtle">
        Es wird die ausgewählte Datei verarbeitet. Entfernen Sie die Datei, um stattdessen
        eingefügten Text zu anonymisieren.
      </p>
    </div>

    <!-- Advanced settings: default-policy editor (collapsed by default). -->
    <section class="rounded-card border border-default bg-surface">
      <button
        type="button"
        class="flex w-full items-center gap-2 rounded-card px-4 py-3 text-sm font-medium text-content transition-colors hover:bg-surface-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-expanded="advancedOpen"
        aria-controls="advanced-settings"
        @click="advancedOpen = !advancedOpen"
      >
        <ChevronDown
          class="h-4 w-4 shrink-0 transition-transform"
          :class="advancedOpen ? '' : '-rotate-90'"
          aria-hidden="true"
        />
        Erweiterte Einstellungen
        <StatusBadge v-if="session.advancedCustomized" label="angepasst" color="purple" />
      </button>
      <div v-if="advancedOpen" id="advanced-settings" class="border-t border-default px-4 py-4">
        <PolicyEditor />
      </div>
    </section>

    <!-- Submit -->
    <div class="flex items-center gap-3">
      <BaseButton size="lg" :disabled="!canSubmit" @click="submit"> Anonymisieren </BaseButton>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, FileText, UploadCloud } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import PolicyEditor from '@/components/anonymizer/PolicyEditor.vue'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { extractApiErrorMessage } from '@/utils/errors'

const session = useSessionStore()
const toast = useToast()

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const pastedText = ref('')
const dragActive = ref(false)
const advancedOpen = ref(false)

const loading = computed(() => session.phase === 'loading')
const canSubmit = computed(
  () => !loading.value && (selectedFile.value !== null || pastedText.value.trim().length > 0),
)

/** Name shown on the processing card (captured when the run starts). */
const processingName = ref('Dokument')

/** Streamed overall percent (null → indeterminate shimmer). */
const percent = computed(() => session.progressPercent)
const roundedPercent = computed(() => (percent.value === null ? null : Math.round(percent.value)))

/** German label for the current pipeline stage. */
const stageLabel = computed(() => {
  const progress = session.progress
  if (progress === null) return 'Dokument wird verarbeitet …'
  switch (progress.stage) {
    case 'ocr':
      return `Texterkennung (OCR): Seite ${progress.done} von ${progress.total}`
    case 'detection':
      return `KI-Erkennung läuft: Abschnitt ${progress.done} von ${progress.total}`
    case 'recheck':
      return 'Abschließende Prüfung des Ergebnisses …'
    default:
      return 'Dokument wird verarbeitet …'
  }
})

const fileSizeLabel = computed(() => {
  const size = selectedFile.value?.size ?? 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
})

function openFilePicker() {
  if (loading.value) return
  fileInput.value?.click()
}

const ACCEPTED_EXTENSIONS = ['.txt', '.pdf', '.docx']

function acceptFile(file: File) {
  const name = file.name.toLowerCase()
  const isAccepted =
    ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension)) || file.type === 'text/plain'
  if (!isAccepted) {
    toast.error('Dateityp nicht unterstützt. Erlaubt sind .txt, .pdf und .docx.')
    return
  }
  selectedFile.value = file
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) acceptFile(file)
  // Allow re-selecting the same file later.
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragActive.value = false
  if (loading.value) return
  const file = event.dataTransfer?.files?.[0]
  if (file) acceptFile(file)
}

function clearFile() {
  selectedFile.value = null
}

async function submit() {
  if (!canSubmit.value) return
  processingName.value = selectedFile.value?.name ?? 'Eingefügter Text'
  try {
    if (selectedFile.value) {
      await session.submitFile(selectedFile.value)
    } else {
      await session.submitText(pastedText.value)
    }
    // Clear the inputs only after a successful run, so a failed request
    // doesn't wipe the user's document.
    selectedFile.value = null
    pastedText.value = ''
  } catch (err) {
    toast.error(extractApiErrorMessage(err))
  }
}
</script>

<style scoped>
/* Indeterminate shimmer: a third-width bar sweeping across the track until
   the first streamed progress event arrives. */
@keyframes progress-shimmer {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(300%);
  }
}
.progress-shimmer {
  animation: progress-shimmer 1.4s ease-in-out infinite;
}
</style>
