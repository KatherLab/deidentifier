<template>
  <!-- The search of ONE panel, in that panel's header: no "which view did you
       mean?" step between the reviewer and the answer. Panels the app cannot
       mark a hit in (the PDF viewers) have no search bar — see
       `isSearchablePanel`. -->
  <div v-if="searchable" class="flex max-w-full items-center">
    <template v-if="open">
      <div
        class="flex min-w-0 flex-wrap items-center gap-1 rounded-card border border-strong bg-surface px-1.5 py-1"
        role="search"
      >
        <Search class="h-3.5 w-3.5 shrink-0 text-content-subtle" aria-hidden="true" />
        <input
          :id="PANEL_SEARCH_INPUT_ID"
          v-model="session.searchQuery"
          type="search"
          autocomplete="off"
          spellcheck="false"
          :aria-label="t('search.label')"
          :placeholder="t('search.placeholder')"
          class="w-40 min-w-0 bg-transparent px-1 py-0.5 text-sm text-content placeholder:text-content-subtle focus:outline-none"
          @keydown.enter.exact.prevent="session.stepSearch(1)"
          @keydown.enter.shift.prevent="session.stepSearch(-1)"
          @keydown.esc.prevent="session.closeSearch()"
        />
        <span class="px-1 text-xs tabular-nums text-content-muted" aria-hidden="true">{{
          counterText
        }}</span>
        <span class="sr-only" aria-live="polite">{{ counterLabel }}</span>
        <button
          type="button"
          :class="navButtonClass"
          :disabled="total === 0"
          :aria-label="t('search.previous')"
          :title="t('search.previous')"
          @click="session.stepSearch(-1)"
        >
          <ChevronUp class="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <button
          type="button"
          :class="navButtonClass"
          :disabled="total === 0"
          :aria-label="t('search.next')"
          :title="t('search.next')"
          @click="session.stepSearch(1)"
        >
          <ChevronDown class="h-3.5 w-3.5" aria-hidden="true" />
        </button>
        <button
          type="button"
          :class="navButtonClass"
          :aria-label="t('search.close')"
          :title="t('search.close')"
          @click="session.closeSearch()"
        >
          <X class="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
    </template>
    <button
      v-else
      type="button"
      :class="navButtonClass"
      :aria-label="t('search.open')"
      :title="t('search.open_title')"
      @click="session.openSearch(panel)"
    >
      <Search class="h-4 w-4" aria-hidden="true" />
    </button>
  </div>
</template>

<script lang="ts">
/**
 * Fixed id — only ONE panel search is open at a time, so the keyboard shortcut
 * can focus it without a template ref that would be ambiguous across the four
 * panel headers (same pattern as `EntityDetailPanel`'s type select).
 */
export const PANEL_SEARCH_INPUT_ID = 'panel-search-input'
</script>

<script setup lang="ts">
import { computed, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, ChevronUp, Search, X } from '@lucide/vue'
import { useSessionStore } from '@/stores/session'
import type { ResultPanelId } from '@/stores/session'

interface Props {
  /** The panel this control belongs to — searching is always panel-scoped. */
  panel: ResultPanelId
}

const props = defineProps<Props>()

const { t } = useI18n()
const session = useSessionStore()

const searchable = computed(() => session.isSearchablePanel(props.panel))
const open = computed(() => session.searchPanel === props.panel)
const total = computed(() => session.searchMatches.length)
/** 1-based, for the counter. */
const current = computed(() => (total.value === 0 ? 0 : session.searchMatchIndex + 1))
const hasQuery = computed(() => session.searchQuery.trim().length > 0)

const counterText = computed(() => {
  if (!hasQuery.value) return ''
  if (total.value === 0) return t('search.no_matches')
  return t('search.count', { current: current.value, total: total.value })
})

/** The same information as a sentence, announced as the reviewer types. */
const counterLabel = computed(() => {
  if (!hasQuery.value) return ''
  if (total.value === 0) return t('search.no_matches')
  return t('search.count_label', { current: current.value, total: total.value })
})

const navButtonClass =
  'rounded-card p-1 text-content-muted transition-colors hover:bg-surface-muted hover:text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40 disabled:hover:bg-transparent'

// Opening the bar puts the cursor in it — including when Ctrl/Cmd+F moves the
// search from one panel to another.
watch(open, (isOpen) => {
  if (!isOpen) return
  void nextTick(() => document.getElementById(PANEL_SEARCH_INPUT_ID)?.focus())
})
</script>
