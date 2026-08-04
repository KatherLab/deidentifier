/**
 * Session store — the ONLY place document content and results live.
 *
 * Privacy rule: never write document content or results to localStorage /
 * sessionStorage. All state here is in-memory only and disappears on reload.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { anonymizeApi } from '@/services/anonymizeApi'
import { anonymizeFileStream, anonymizeTextStream } from '@/services/anonymizeStream'
import { statusApi } from '@/services/statusApi'
import { extractPdfExportErrorMessage, isExpiredResultError } from '@/utils/errors'
import { DEFAULT_POLICY, policyDeviations } from '@/utils/policy'
import type {
  AnonymizeResponse,
  AnonymizedEntity,
  CustomRules,
  DetectorStatus,
  EntityType,
  ExternalEndpoint,
  Override,
  PolicyMap,
  StatusResponse,
  StreamProgressEvent,
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
   * Live progress of the current FRESH run (streamed from
   * /anonymize/stream). Null before the first event arrives (indeterminate
   * bar) and outside of runs. Override re-runs don't stream and never set it.
   */
  const progress = ref<StreamProgressEvent | null>(null)
  /**
   * Highest overall percent seen in the current run — kept as a max so the
   * bar is monotonically non-decreasing even if stage math would dip.
   */
  const progressMaxPercent = ref(0)
  /** True once any OCR event arrived (scanned PDF → OCR gets its own span). */
  let progressSawOcr = false

  /**
   * Overall progress percent (0–100) of the current run, or null while
   * indeterminate. Stage weights: with OCR (scanned PDF) ocr spans 0–45%,
   * detection 45–90%, recheck 90–100%; without OCR detection spans 0–85% and
   * recheck 85–100%.
   */
  const progressPercent = computed<number | null>(() =>
    progress.value === null ? null : progressMaxPercent.value,
  )

  /** [base, span] of a stage in the overall percent scale. */
  function stageSpan(stage: StreamProgressEvent['stage'], sawOcr: boolean): [number, number] {
    if (sawOcr) {
      if (stage === 'ocr') return [0, 45]
      if (stage === 'detection') return [45, 45]
      return [90, 10]
    }
    if (stage === 'detection') return [0, 85]
    return [85, 15]
  }

  /** onProgress callback for the streaming endpoints. */
  function onStreamProgress(event: StreamProgressEvent): void {
    if (event.stage === 'ocr') progressSawOcr = true
    progress.value = event
    const [base, span] = stageSpan(event.stage, progressSawOcr)
    const fraction = Math.min(event.done / Math.max(event.total, 1), 1)
    progressMaxPercent.value = Math.min(
      Math.max(progressMaxPercent.value, base + span * fraction),
      100,
    )
  }

  function clearProgress(): void {
    progress.value = null
    progressMaxPercent.value = 0
    progressSawOcr = false
  }

  /**
   * The ORIGINAL uploaded file of the current result (memory only — NEVER
   * persisted). Needed for the redacted-PDF export, which re-sends the file
   * because the server stores nothing. Null for pasted-text runs.
   */
  const sourceFile = ref<File | null>(null)

  /**
   * Editable default policy (advanced settings on the landing page). Memory
   * only — never persisted. Only DEVIATIONS from DEFAULT_POLICY are sent to
   * the backend (as the request-level `policy` field on every request).
   */
  const policy = ref<Record<EntityType, TransformationType>>({ ...DEFAULT_POLICY })

  /**
   * Custom rules (advanced settings, "Eigene Regeln"). Memory only — never
   * persisted. `customInstruction` and `redactTerms` affect DETECTION and thus
   * only apply to the next full run; `preserveTerms` applies at transformation
   * time and is also sent on cached re-runs.
   */
  const customInstruction = ref('')
  const redactTerms = ref<string[]>([])
  const preserveTerms = ref<string[]>([])

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

  /**
   * Object URL for the ORIGINAL uploaded PDF (the "Original" result panel).
   * Created lazily on first activation of that panel, revoked on reset/new
   * result. Memory only — never persisted.
   */
  const originalPreviewUrl = ref<string | null>(null)

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

  /** The deviations from the default policy to send with requests (or null). */
  const policyOverrides = computed<PolicyMap | null>(() => policyDeviations(policy.value))

  /** True when the user changed any policy entry (badge in advanced settings). */
  const policyCustomized = computed(() => policyOverrides.value !== null)

  /** The custom rules to send with requests (trimmed), or null when empty. */
  const customRules = computed<CustomRules | null>(() => {
    const instruction = customInstruction.value.trim()
    if (
      instruction.length === 0 &&
      redactTerms.value.length === 0 &&
      preserveTerms.value.length === 0
    ) {
      return null
    }
    return {
      customInstruction: instruction,
      redactTerms: [...redactTerms.value],
      preserveTerms: [...preserveTerms.value],
    }
  })

  /** True when policy OR custom rules deviate from the defaults (badge). */
  const advancedCustomized = computed(() => policyCustomized.value || customRules.value !== null)

  function setPolicyTransformation(type: EntityType, transformation: TransformationType): void {
    policy.value = { ...policy.value, [type]: transformation }
  }

  /** Reset ALL advanced settings: policy AND custom rules ("Zurücksetzen"). */
  function resetAdvancedSettings(): void {
    policy.value = { ...DEFAULT_POLICY }
    customInstruction.value = ''
    redactTerms.value = []
    preserveTerms.value = []
  }

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

  /**
   * Lazily create the object URL for the ORIGINAL uploaded PDF (used by the
   * "Original" panel for PDF sources). Returns null when the original file is
   * gone or the result is not a PDF.
   */
  function ensureOriginalPreviewUrl(): string | null {
    if (originalPreviewUrl.value !== null) return originalPreviewUrl.value
    const file = sourceFile.value
    if (file === null || !isPdfResult(result.value)) return null
    originalPreviewUrl.value = URL.createObjectURL(file)
    return originalPreviewUrl.value
  }

  /** Revoke the original-document object URL, if any. */
  function clearOriginalPreview(): void {
    if (originalPreviewUrl.value !== null) URL.revokeObjectURL(originalPreviewUrl.value)
    originalPreviewUrl.value = null
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
      const { data } = await anonymizeApi.exportPdf(
        file,
        current.request_id,
        [...overrides.value.values()],
        policyOverrides.value,
        customRules.value,
      )
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

  async function run(request: () => Promise<AnonymizeResponse>): Promise<void> {
    phase.value = 'loading'
    clearProgress()
    try {
      result.value = await request()
      selectedEntityIndex.value = null
      overrides.value = new Map()
      // A new result invalidates any previous document previews.
      clearPdfPreview()
      clearOriginalPreview()
      phase.value = 'result'
    } catch (err) {
      phase.value = 'idle'
      throw err
    } finally {
      clearProgress()
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
        // Cached path: only preserve_terms may be sent — redact terms and the
        // custom instruction are already baked into the cached detection.
        response = (
          await anonymizeApi.rerunWithOverrides(
            requestId,
            allOverrides,
            policyOverrides.value,
            preserveTerms.value,
          )
        ).data
      } catch (err) {
        if (!isExpiredResultError(err)) throw err
        // Cache expired — re-detect from the original text with the same
        // overrides (full custom rules apply again); the response carries a
        // fresh request_id.
        response = (
          await anonymizeApi.anonymizeText(
            sourceText,
            allOverrides,
            policyOverrides.value,
            customRules.value,
          )
        ).data
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

  /**
   * Manually redact an arbitrary text region (mouse selection in the source
   * review). The offsets are Unicode CODE POINTS into `source_text`; because
   * they don't match a detected entity, the backend turns the override into a
   * user-defined span (detector `user_manual`, `metadata.user_manual`) on the
   * re-run. Removing the override again (resetEntityOverride) undoes it.
   */
  function addManualRedaction(start: number, end: number): Promise<void> {
    if (!result.value) return Promise.resolve()
    const previous = new Map(overrides.value)
    const text = Array.from(result.value.source_text).slice(start, end).join('')
    overrides.value.set(overrideKey({ start, end }), { start, end, text, transformation: 'REMOVE' })
    return rerunOverrides(previous)
  }

  /** Remove any override for this entity and re-run with the remaining ones. */
  function resetEntityOverride(entity: AnonymizedEntity): Promise<void> {
    const key = overrideKey(entity)
    const previous = new Map(overrides.value)
    if (!overrides.value.delete(key)) return Promise.resolve()
    return rerunOverrides(previous)
  }

  /**
   * Anonymize pasted text via the STREAMING endpoint (live progress).
   * Rejects with the API error (caller shows a toast).
   */
  async function submitText(text: string): Promise<void> {
    await run(() =>
      anonymizeTextStream(text, policyOverrides.value, customRules.value, onStreamProgress),
    )
    sourceFile.value = null
  }

  /**
   * Anonymize an uploaded file via the STREAMING endpoint (live progress).
   * Rejects with the API error (caller shows a toast).
   */
  async function submitFile(file: File): Promise<void> {
    await run(() =>
      anonymizeFileStream(file, policyOverrides.value, customRules.value, onStreamProgress),
    )
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
    clearOriginalPreview()
    clearProgress()
    phase.value = 'idle'
  }

  return {
    phase,
    progress,
    progressPercent,
    result,
    sourceFile,
    selectedEntityIndex,
    selectedEntity,
    entityCounts,
    overrides,
    rerunning,
    policy,
    policyOverrides,
    policyCustomized,
    customInstruction,
    redactTerms,
    preserveTerms,
    customRules,
    advancedCustomized,
    setPolicyTransformation,
    resetAdvancedSettings,
    pdfPreviewUrl,
    pdfPreviewBlob,
    pdfPreviewLoading,
    pdfPreviewError,
    refreshPdfPreview,
    originalPreviewUrl,
    ensureOriginalPreviewUrl,
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
    addManualRedaction,
    resetEntityOverride,
    reset,
  }
})
