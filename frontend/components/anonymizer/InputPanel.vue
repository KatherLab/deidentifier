<template>
  <!--
    Processing state: shown only until the FIRST document of the batch
    finishes — then the app switches to the result view and the rest keep
    processing in the background. Multi-document batches get the combined
    batch progress card; single-document runs keep the classic progress card
    of the one running document (streamed from the backend).
  -->
  <section v-if="loading && session.documents.length > 1" class="flex flex-col items-center py-10">
    <BatchProgress />
  </section>
  <section v-else-if="loading && session.loadingDocument" class="flex flex-col items-center py-10">
    <ProcessingCard :document="session.loadingDocument" />
  </section>

  <section v-else class="space-y-6">
    <!-- Drag-and-drop zone (multiple files → one document per file) -->
    <div
      class="rounded-modal border-2 border-dashed p-8 text-center transition-colors cursor-pointer"
      :class="
        dragActive
          ? 'border-primary bg-primary-soft'
          : 'border-strong bg-surface-muted hover:border-primary'
      "
      role="button"
      tabindex="0"
      :aria-label="t('input.dropzone_label')"
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
        multiple
        class="hidden"
        @change="onFileChange"
      />
      <div class="flex flex-col items-center gap-2">
        <UploadCloud class="h-10 w-10 text-content-subtle" aria-hidden="true" />
        <template v-if="selectedFiles.length === 0">
          <p class="text-sm font-medium text-content">{{ t('input.dropzone_prompt') }}</p>
          <p class="text-xs text-content-subtle">{{ t('input.dropzone_hint') }}</p>
        </template>
        <template v-else>
          <ul class="w-full max-w-md space-y-1 text-left">
            <li
              v-for="(file, index) in selectedFiles"
              :key="`${file.name}-${index}`"
              class="flex items-center gap-2 rounded-card bg-surface px-3 py-1.5 text-sm"
            >
              <FileText class="h-4 w-4 shrink-0 text-content-subtle" aria-hidden="true" />
              <span class="min-w-0 flex-1 truncate font-medium text-content" :title="file.name">
                {{ file.name }}
              </span>
              <span class="shrink-0 text-xs text-content-subtle">{{
                fileSizeLabel(file.size)
              }}</span>
              <button
                type="button"
                class="shrink-0 rounded-card p-0.5 text-content-subtle transition-colors hover:text-content"
                :aria-label="t('input.remove_file', { name: file.name })"
                @click.stop="removeFile(index)"
              >
                <X class="h-4 w-4" aria-hidden="true" />
              </button>
            </li>
          </ul>
          <p class="text-xs text-content-subtle">{{ t('input.dropzone_add_more') }}</p>
          <BaseButton variant="link" tone="gray" @click.stop="clearFiles">
            {{ t('input.clear_files') }}
          </BaseButton>
        </template>
      </div>
    </div>

    <!-- Divider -->
    <div class="flex items-center gap-3" aria-hidden="true">
      <div class="h-px flex-1 bg-(--color-default-border)"></div>
      <span class="text-xs uppercase tracking-wide text-content-subtle">{{
        t('input.divider')
      }}</span>
      <div class="h-px flex-1 bg-(--color-default-border)"></div>
    </div>

    <!-- Paste textarea -->
    <div>
      <label for="paste-text" class="sr-only">{{ t('input.paste_label') }}</label>
      <textarea
        id="paste-text"
        v-model="pastedText"
        rows="10"
        :disabled="selectedFiles.length > 0 || loading"
        :placeholder="t('input.paste_placeholder')"
        class="w-full rounded-card border border-strong bg-surface p-3 text-sm text-content placeholder:text-content-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      ></textarea>
      <p v-if="selectedFiles.length > 0" class="mt-1 text-xs text-content-subtle">
        {{ t('input.files_take_precedence') }}
      </p>
    </div>

    <!-- Advanced settings: default-policy editor (collapsed by default). The
         settings are captured ONCE at submit and apply to every document of
         the batch. -->
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
        {{ t('input.advanced') }}
        <StatusBadge
          v-if="session.advancedCustomized"
          :label="t('input.advanced_customized')"
          color="purple"
        />
      </button>
      <div v-if="advancedOpen" id="advanced-settings" class="border-t border-default px-4 py-4">
        <PolicyEditor />
      </div>
    </section>

    <!-- Submit -->
    <div class="space-y-2">
      <BaseButton size="lg" :disabled="!canSubmit" @click="submit">{{ submitLabel }}</BaseButton>
      <p class="text-xs text-content-subtle">{{ t('input.disclaimer') }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, FileText, UploadCloud, X } from '@lucide/vue'
import BaseButton from '@/components/common/BaseButton.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import BatchProgress from '@/components/anonymizer/BatchProgress.vue'
import PolicyEditor from '@/components/anonymizer/PolicyEditor.vue'
import ProcessingCard from '@/components/anonymizer/ProcessingCard.vue'
import { useSessionStore } from '@/stores/session'
import { useToast } from '@/composables/useToast'
import { formatDecimal } from '@/utils/format'

const { t } = useI18n()
const session = useSessionStore()
const toast = useToast()

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFiles = ref<File[]>([])
const pastedText = ref('')
const dragActive = ref(false)
const advancedOpen = ref(false)

const loading = computed(() => session.phase === 'loading')
const canSubmit = computed(
  () => !loading.value && (selectedFiles.value.length > 0 || pastedText.value.trim().length > 0),
)

const submitLabel = computed(() =>
  selectedFiles.value.length > 1
    ? t('input.submit_many', { count: selectedFiles.value.length })
    : t('input.submit'),
)

function fileSizeLabel(size: number): string {
  if (size < 1024) return t('input.size_bytes', { size: formatDecimal(size) })
  if (size < 1024 * 1024) return t('input.size_kb', { size: formatDecimal(size / 1024) })
  return t('input.size_mb', { size: formatDecimal(size / (1024 * 1024)) })
}

function openFilePicker() {
  if (loading.value) return
  fileInput.value?.click()
}

const ACCEPTED_EXTENSIONS = ['.txt', '.pdf', '.docx']

function acceptFiles(files: Iterable<File>) {
  for (const file of files) {
    const name = file.name.toLowerCase()
    const isAccepted =
      ACCEPTED_EXTENSIONS.some((extension) => name.endsWith(extension)) ||
      file.type === 'text/plain'
    if (!isAccepted) {
      toast.error(t('input.unsupported_file', { name: file.name }))
      continue
    }
    selectedFiles.value.push(file)
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files) acceptFiles(input.files)
  // Allow re-selecting the same files later.
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragActive.value = false
  if (loading.value) return
  if (event.dataTransfer?.files) acceptFiles(event.dataTransfer.files)
}

function removeFile(index: number) {
  selectedFiles.value.splice(index, 1)
}

function clearFiles() {
  selectedFiles.value = []
}

/**
 * Start the batch: one document per selected file (all processed in
 * parallel), or a single document for pasted text. Processing errors surface
 * per document in the result view — no toast handling needed here.
 */
function submit() {
  if (!canSubmit.value) return
  if (selectedFiles.value.length > 0) {
    session.submitFiles([...selectedFiles.value])
  } else {
    session.submitText(pastedText.value)
  }
  selectedFiles.value = []
  pastedText.value = ''
}
</script>
