<template>
  <section v-if="totalCount > 0">
    <button
      type="button"
      class="flex items-center gap-2 rounded-card text-sm font-semibold text-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :aria-expanded="open"
      @click="open = !open"
    >
      <ChevronDown
        class="h-4 w-4 shrink-0 transition-transform"
        :class="open ? '' : '-rotate-90'"
        aria-hidden="true"
      />
      Hinweise &amp; Warnungen
      <span class="font-normal text-content-subtle">({{ totalCount }})</span>
    </button>
    <ul v-if="open" class="mt-2 space-y-2">
      <li
        v-for="(warning, index) in validationWarnings"
        :key="`validation-${index}`"
        class="rounded-card px-3 py-2 text-sm"
        :class="getBannerClass(severityColor(warning.severity))"
      >
        <div class="flex flex-wrap items-start gap-2">
          <p class="min-w-0 flex-1">{{ warning.message }}</p>
          <button
            v-if="warning.start !== null && warning.end !== null"
            type="button"
            class="shrink-0 text-xs font-medium underline underline-offset-2 hover:opacity-80"
            @click="emit('locate', warning)"
          >
            Im Text anzeigen
          </button>
        </div>
        <!-- Severity + backend category slug: diagnostics, expert-only (the
             severity is already carried by the banner color for everyone). -->
        <p v-if="settings.expertMode" class="mt-1 text-xs uppercase tracking-wide opacity-80">
          {{ severityLabel(warning.severity) }} · {{ warning.category }}
        </p>
      </li>
      <!-- General warnings are plain strings from the backend (OCR quality
           hints, docling fallback notes, …) — rendered as informational items,
           separate from the structured validation warnings above. -->
      <li
        v-for="(warning, index) in generalWarnings"
        :key="`general-${index}`"
        class="rounded-card px-3 py-2 text-sm"
        :class="getBannerClass('blue')"
      >
        {{ warning }}
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown } from '@lucide/vue'
import { useSettingsStore } from '@/stores/settings'
import { getBannerClass } from '@/utils/statusStyles'
import { severityColor, severityLabel } from '@/utils/entityLabels'
import type { ValidationWarning } from '@/types/anonymizer'

interface Props {
  validationWarnings: ValidationWarning[]
  generalWarnings: string[]
  /** Start expanded (validation not passed) or collapsed (all clear). */
  initiallyOpen?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  initiallyOpen: true,
})

const emit = defineEmits<{
  (e: 'locate', warning: ValidationWarning): void
}>()

const settings = useSettingsStore()

const open = ref(props.initiallyOpen)

const totalCount = computed(() => props.validationWarnings.length + props.generalWarnings.length)
</script>
