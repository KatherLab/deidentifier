<template>
  <!-- Plain document text (original source, anonymized output) with the panel
       search's hits marked. Without a query this renders exactly one segment,
       i.e. the text as it was before. -->
  <div ref="container">
    <template v-for="segment in segments" :key="segment.key">
      <mark
        v-if="segment.matchIndex !== null"
        :class="[
          SEARCH_MATCH_CLASS,
          segment.matchIndex === activeMatchIndex ? SEARCH_MATCH_ACTIVE_CLASS : '',
        ]"
        :data-match-index="segment.matchIndex"
        :aria-current="segment.matchIndex === activeMatchIndex ? 'true' : undefined"
        v-text="segment.text"
      ></mark>
      <!-- v-text: the container is whitespace-pre-wrap, so template
           indentation must not leak into the document text. -->
      <span v-else v-text="segment.text"></span>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { buildHighlightSegments, type MatchRange } from '@/utils/textSegments'
import { SEARCH_MATCH_ACTIVE_CLASS, SEARCH_MATCH_CLASS } from '@/utils/entityLabels'

interface Props {
  text: string
  /** Hits to mark, in code point offsets (empty when no search is open). */
  matches?: MatchRange[]
  /** Index of the hit the reviewer is currently on, or null. */
  activeMatchIndex?: number | null
}

const props = withDefaults(defineProps<Props>(), {
  matches: () => [],
  activeMatchIndex: null,
})

const segments = computed(() => buildHighlightSegments(props.text, [], [], props.matches))

const container = ref<HTMLElement | null>(null)

/** Bring the active hit on screen — the panel scrolls, the page does not. */
watch(
  () => [props.activeMatchIndex, props.matches] as const,
  async () => {
    if (props.activeMatchIndex === null) return
    await nextTick()
    container.value
      ?.querySelector(`[data-match-index="${props.activeMatchIndex}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  },
)
</script>
