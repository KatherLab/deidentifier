<template>
  <section v-if="validationWarnings.length > 0 || generalWarnings.length > 0" class="space-y-2">
    <h3 class="text-sm font-semibold text-content">Hinweise &amp; Warnungen</h3>
    <ul class="space-y-2">
      <li
        v-for="(warning, index) in validationWarnings"
        :key="`validation-${index}`"
        class="rounded-card px-3 py-2 text-sm"
        :class="getBannerClass(severityColor(warning.severity))"
      >
        <div class="flex flex-wrap items-center gap-2">
          <StatusBadge
            :label="severityLabel(warning.severity)"
            :color="severityColor(warning.severity)"
          />
          <span class="text-xs font-medium uppercase tracking-wide opacity-80">
            {{ warning.category }}
          </span>
          <button
            v-if="warning.start !== null && warning.end !== null"
            type="button"
            class="ml-auto text-xs font-medium underline underline-offset-2 hover:opacity-80"
            @click="emit('locate', warning)"
          >
            Im Text anzeigen
          </button>
        </div>
        <p class="mt-1">{{ warning.message }}</p>
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
        <div class="flex items-center gap-2">
          <StatusBadge label="Hinweis" color="blue" />
          <span>{{ warning }}</span>
        </div>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import StatusBadge from '@/components/common/StatusBadge.vue'
import { getBannerClass } from '@/utils/statusStyles'
import { severityColor, severityLabel } from '@/utils/entityLabels'
import type { ValidationWarning } from '@/types/anonymizer'

interface Props {
  validationWarnings: ValidationWarning[]
  generalWarnings: string[]
}

defineProps<Props>()

const emit = defineEmits<{
  (e: 'locate', warning: ValidationWarning): void
}>()
</script>
