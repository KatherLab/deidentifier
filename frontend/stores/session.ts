/**
 * Session store — the ONLY place document content and results live.
 *
 * Privacy rule: never write document content or results to localStorage /
 * sessionStorage. All state here is in-memory only and disappears on reload.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { anonymizeApi } from '@/services/anonymizeApi'
import { statusApi } from '@/services/statusApi'
import { extractPdfExportErrorMessage, isExpiredResultError } from '@/utils/errors'
import type {
  AnonymizeResponse,
  AnonymizedEntity,
  DetectorStatus,
  EntityType,
  ExternalEndpoint,
  Override,
  StatusResponse,
  TransformationType,
} from '@/types/anonymizer'

export type SessionPhase = 'idle' | 'loading' | 'result'

/** Stable identity of a detected entity across re-runs (offsets don't move). */
export function overrideKey(entity: { start: number; end: number }): string {
  return `${entity.start}:${entity.end}`
}

export const useSessionStore = defineStore('session', () => {
  const phase = ref<SessionPhase>('idle')
  const result = ref<AnonymizeResponse | null>(null)
  const selectedEntityIndex = ref<number | null>(null)

  /**
   * The ORIGINAL uploaded file of the current result (memory only — NEVER
   * persisted). Needed for the redacted-PDF export, which re-sends the file
   * because the server stores nothing. Null for pasted-text runs.
   */
  const sourceFile = ref<File | null>(null)

  /** Accumulated per-entity overrides, keyed by `${start}:${end}`. */
  const overrides = ref<Map<string, Override>>(new Map())
  /** True while an override re-run is in flight (result view stays visible). */
  const rerunning = ref(false)

  /**
   * Redacted-PDF preview of the current result (memory only — NEVER
   * persisted). `pdfPreviewUrl` is an object URL for the exported PDF blob;
   * it is revoked whenever it is replaced or cleared.
   */
  const pdfPreviewUrl = ref<string | null>(null)
  /** The exported PDF blob backing `pdfPreviewUrl` (reused for downloads). */
  const pdfPreviewBlob = ref<Blob | null>(null)
  const pdfPreviewLoading = ref(false)
  const pdfPreviewError = ref<string | null>(null)
  /** Bumped on every refresh/clear so stale in-flight responses are ignored. */
  let pdfPreviewToken = 0

  const status = ref<StatusResponse | null>(null)
  const externalBannerDismissed = ref(false)

  const selectedEntity = computed<AnonymizedEntity | null>(() => {
    if (result.value === null || selectedEntityIndex.value === null) return null
    return result.value.entities[selectedEntityIndex.value] ?? null
  })

  /** Entity counts by type, in a stable (first-seen) order. */
  const entityCounts = computed<{ type: EntityType; count: number }[]>(() => {
    if (!result.value) return []
    const counts = new Map<EntityType, number>()
    for (const entity of result.value.entities) {
      counts.set(entity.entity_type, (counts.get(entity.entity_type) ?? 0) + 1)
    }
    return [...counts.entries()].map(([type, count]) => ({ type, count }))
  })

  /** External (non-local) endpoints that document content is sent to. */
  const externalEndpoints = computed<ExternalEndpoint[]>(
    () => status.value?.external_endpoints.filter((endpoint) => !endpoint.local) ?? [],
  )

  const showExternalBanner = computed(
    () => externalEndpoints.value.length > 0 && !externalBannerDismissed.value,
  )

  /** Detectors that are enabled but not ready (e.g. LLM not configured). */
  const notReadyDetectors = computed<DetectorStatus[]>(
    () => status.value?.detectors.filter((detector) => detector.enabled && !detector.ready) ?? [],
  )

  /** The pending override for an entity, if any. */
  function overrideFor(entity: { start: number; end: number }): Override | undefined {
    return overrides.value.get(overrideKey(entity))
  }

  async function fetchStatus(): Promise<void> {
    try {
      status.value = (await statusApi.getStatus()).data
    } catch {
      // Backend not reachable yet — errors surface on submit instead.
      status.value = null
    }
  }

  function dismissExternalBanner(): void {
    externalBannerDismissed.value = true
  }

  /** True when the response was produced from a PDF (redactable source). */
  function isPdfResult(response: AnonymizeResponse | null): boolean {
    return response?.source_type === 'pdf' || response?.source_type === 'pdf-ocr'
  }

  /** Revoke the preview object URL and drop all preview state. */
  function clearPdfPreview(): void {
    pdfPreviewToken += 1
    if (pdfPreviewUrl.value !== null) URL.revokeObjectURL(pdfPreviewUrl.value)
    pdfPreviewUrl.value = null
    pdfPreviewBlob.value = null
    pdfPreviewLoading.value = false
    pdfPreviewError.value = null
  }

  /**
   * (Re-)export the redacted PDF for the current result with all accumulated
   * overrides and show it as an inline preview. No-op for non-PDF results or
   * when the original file is gone. Called automatically after a successful
   * PDF upload and after every successful override re-run, so the preview
   * always reflects the user's overrides. Can take up to a minute for scans
   * on a backend cache miss (hence the dedicated loading state).
   */
  async function refreshPdfPreview(): Promise<void> {
    const current = result.value
    const file = sourceFile.value
    if (current === null || file === null || !isPdfResult(current)) return

    const token = ++pdfPreviewToken
    pdfPreviewLoading.value = true
    pdfPreviewError.value = null
    try {
      const { data } = await anonymizeApi.exportPdf(file, current.request_id, [
        ...overrides.value.values(),
      ])
      if (token !== pdfPreviewToken) return
      if (pdfPreviewUrl.value !== null) URL.revokeObjectURL(pdfPreviewUrl.value)
      pdfPreviewBlob.value = data
      pdfPreviewUrl.value = URL.createObjectURL(data)
    } catch (err) {
      if (token !== pdfPreviewToken) return
      pdfPreviewError.value = await extractPdfExportErrorMessage(err)
    } finally {
      if (token === pdfPreviewToken) pdfPreviewLoading.value = false
    }
  }

  async function run(request: () => ReturnType<typeof anonymizeApi.anonymizeText>): Promise<void> {
    phase.value = 'loading'
    try {
      const { data } = await request()
      result.value = data
      selectedEntityIndex.value = null
      overrides.value = new Map()
      // A new result invalidates any previous redacted-PDF preview.
      clearPdfPreview()
      phase.value = 'result'
    } catch (err) {
      phase.value = 'idle'
      throw err
    }
  }

  /**
   * Re-run the current result with all accumulated overrides. Tries the cheap
   * cached path first ({request_id, overrides}); on 410 (cache expired) it
   * automatically retries ONCE with the full source text plus the same
   * overrides and adopts the new request_id. The result view stays visible
   * (`rerunning` instead of `phase`); on failure the override map is rolled
   * back and the error rethrown (caller shows a toast).
   */
  async function rerunOverrides(previousOverrides: Map<string, Override>): Promise<void> {
    if (!result.value) return
    const requestId = result.value.request_id
    const sourceText = result.value.source_text
    const allOverrides = [...overrides.value.values()]
    const selectedKey = selectedEntity.value !== null ? overrideKey(selectedEntity.value) : null

    rerunning.value = true
    try {
      let response: AnonymizeResponse
      try {
        response = (await anonymizeApi.rerunWithOverrides(requestId, allOverrides)).data
      } catch (err) {
        if (!isExpiredResultError(err)) throw err
        // Cache expired — re-detect from the original text with the same
        // overrides; the response carries a fresh request_id.
        response = (await anonymizeApi.anonymizeText(sourceText, allOverrides)).data
      }
      result.value = response
      // Re-select the same entity by offsets (indices may shift on re-runs).
      selectedEntityIndex.value =
        selectedKey === null ? null : indexOfEntityKey(response.entities, selectedKey)
      // The preview must reflect the new overrides (no-op for non-PDF results).
      void refreshPdfPreview()
    } catch (err) {
      overrides.value = previousOverrides
      throw err
    } finally {
      rerunning.value = false
    }
  }

  function indexOfEntityKey(entities: AnonymizedEntity[], key: string): number | null {
    const index = entities.findIndex((entity) => overrideKey(entity) === key)
    return index === -1 ? null : index
  }

  /**
   * Set (or merge) an override for one entity and immediately re-run.
   * A type change intentionally drops any transformation override so the
   * default policy for the new type applies.
   */
  function applyEntityOverride(
    entity: AnonymizedEntity,
    patch: { transformation?: TransformationType; entity_type?: EntityType },
  ): Promise<void> {
    const key = overrideKey(entity)
    const previous = new Map(overrides.value)
    const existing = overrides.value.get(key)
    const next: Override = {
      start: entity.start,
      end: entity.end,
      text: entity.text,
    }
    if (patch.entity_type !== undefined) {
      // Type change: keep transformation unset (drop any earlier transformation
      // override) so the default policy for the new type applies.
      next.entity_type = patch.entity_type
    } else {
      if (existing?.entity_type !== undefined) next.entity_type = existing.entity_type
      if (patch.transformation !== undefined) next.transformation = patch.transformation
    }
    overrides.value.set(key, next)
    return rerunOverrides(previous)
  }

  /** Remove any override for this entity and re-run with the remaining ones. */
  function resetEntityOverride(entity: AnonymizedEntity): Promise<void> {
    const key = overrideKey(entity)
    const previous = new Map(overrides.value)
    if (!overrides.value.delete(key)) return Promise.resolve()
    return rerunOverrides(previous)
  }

  /** Anonymize pasted text. Rejects with the API error (caller shows a toast). */
  async function submitText(text: string): Promise<void> {
    await run(() => anonymizeApi.anonymizeText(text))
    sourceFile.value = null
  }

  /** Anonymize an uploaded file. Rejects with the API error (caller shows a toast). */
  async function submitFile(file: File): Promise<void> {
    await run(() => anonymizeApi.anonymizeFile(file))
    sourceFile.value = file
    // For PDF sources, load the redacted-PDF preview right away (not awaited —
    // the text result is already usable while the preview renders).
    void refreshPdfPreview()
  }

  function selectEntity(index: number | null): void {
    selectedEntityIndex.value = index
  }

  /** Drop the current result and return to the input screen. */
  function reset(): void {
    result.value = null
    selectedEntityIndex.value = null
    overrides.value = new Map()
    sourceFile.value = null
    clearPdfPreview()
    phase.value = 'idle'
  }

  return {
    phase,
    result,
    sourceFile,
    selectedEntityIndex,
    selectedEntity,
    entityCounts,
    overrides,
    rerunning,
    pdfPreviewUrl,
    pdfPreviewBlob,
    pdfPreviewLoading,
    pdfPreviewError,
    refreshPdfPreview,
    status,
    externalEndpoints,
    showExternalBanner,
    notReadyDetectors,
    fetchStatus,
    dismissExternalBanner,
    submitText,
    submitFile,
    selectEntity,
    overrideFor,
    applyEntityOverride,
    resetEntityOverride,
    reset,
  }
})
