<template>
  <div>
    <div
      class="flex flex-wrap items-center gap-1.5 rounded-card border border-strong bg-surface px-2 py-1.5 focus-within:ring-2 focus-within:ring-ring"
    >
      <span
        v-for="(term, index) in modelValue"
        :key="`${term}-${index}`"
        class="inline-flex max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-xs"
        :class="getPillClass(tone === 'amber' ? 'amber' : 'gray')"
      >
        <span class="truncate">{{ term }}</span>
        <button
          type="button"
          class="shrink-0 rounded-full hover:opacity-70 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :aria-label="`${term} entfernen`"
          @click="removeAt(index)"
        >
          <X class="h-3 w-3" aria-hidden="true" />
        </button>
      </span>
      <input
        :id="inputId"
        v-model="draft"
        type="text"
        class="min-w-32 flex-1 bg-transparent py-0.5 text-sm text-content placeholder:text-content-subtle focus:outline-none disabled:opacity-50"
        :placeholder="atLimit ? '' : placeholder"
        :maxlength="maxTermLength"
        :disabled="atLimit"
        @keydown.enter.prevent="commitDraft"
        @keydown="onKeydown"
        @blur="commitDraft"
      />
    </div>
    <p v-if="atLimit" class="mt-1 text-xs text-content-subtle">
      Maximal {{ maxItems }} Begriffe möglich.
    </p>
  </div>
</template>

<script setup lang="ts">
/**
 * Chips/tag input: typing a term and pressing Enter or comma (or leaving the
 * field) adds a chip; × removes it. Terms are trimmed, deduplicated
 * (case-insensitively) and capped at `maxItems` × `maxTermLength` characters.
 */
import { computed, ref } from 'vue'
import { X } from '@lucide/vue'
import { getPillClass } from '@/utils/statusStyles'

const props = withDefaults(
  defineProps<{
    modelValue: string[]
    /** id for the inner <input> so an external <label for> can target it. */
    inputId: string
    placeholder?: string
    /** 'amber' tints the chips as a visual caution (e.g. "Nie schwärzen"). */
    tone?: 'default' | 'amber'
    maxItems?: number
    maxTermLength?: number
  }>(),
  {
    placeholder: 'Begriff eingeben, mit Enter hinzufügen',
    tone: 'default',
    maxItems: 100,
    maxTermLength: 200,
  },
)

const emit = defineEmits<{ (event: 'update:modelValue', value: string[]): void }>()

const draft = ref('')

const atLimit = computed(() => props.modelValue.length >= props.maxItems)

/** Add the typed text as chip(s); comma-separated input becomes several. */
function commitDraft() {
  const terms = draft.value
    .split(',')
    .map((term) => term.trim().slice(0, props.maxTermLength))
    .filter((term) => term.length > 0)
  if (terms.length === 0) {
    draft.value = ''
    return
  }
  const next = [...props.modelValue]
  const seen = new Set(next.map((term) => term.toLowerCase()))
  for (const term of terms) {
    if (next.length >= props.maxItems) break
    const key = term.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    next.push(term)
  }
  draft.value = ''
  if (next.length !== props.modelValue.length) emit('update:modelValue', next)
}

function removeAt(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === ',') {
    event.preventDefault()
    commitDraft()
  } else if (event.key === 'Backspace' && draft.value === '' && props.modelValue.length > 0) {
    removeAt(props.modelValue.length - 1)
  }
}
</script>
