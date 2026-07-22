<template>
  <section class="space-y-6">
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

    <!-- Submit -->
    <div class="flex items-center gap-3">
      <BaseButton size="lg" :loading="loading" :disabled="!canSubmit" @click="submit">
        Anonymisieren
      </BaseButton>
      <span v-if="loading" class="text-sm text-content-subtle" aria-live="polite">
        Dokument wird verarbeitet …
      </span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { UploadCloud } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { extractApiErrorMessage } from '@/utils/errors'

const session = useSessionStore()
const toast = useToast()

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const pastedText = ref('')
const dragActive = ref(false)

const loading = computed(() => session.phase === 'loading')
const canSubmit = computed(
  () => !loading.value && (selectedFile.value !== null || pastedText.value.trim().length > 0),
)

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
