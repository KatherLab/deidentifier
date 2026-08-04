/**
 * Session store — the ONLY place document content and results live.
 *
 * Privacy rule: never write document content or results to localStorage /
 * sessionStorage. All state here is in-memory only and disappears on reload.
 *
 * Multi-document model: every submit creates a BATCH of documents (one per
 * dropped file; pasted text is a single-document batch). Each document owns
 * ALL of its per-run state (result, overrides, previews, selection, panels)
 * and runs as one independent `/anonymize/stream` request. Up to
 * MAX_CONCURRENT_STREAMS documents stream at once (browser connection
 * budget); the rest wait as 'queued' and start as slots free — the backend
 * enforces global LLM/OCR concurrency limits and interleaves stage work
 * across requests on its own. All entity/preview/export actions operate on
 * the ACTIVE document, so components keep their existing call sites.
 */
import { computed, reactive, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { anonymizeApi } from '@/services/anonymizeApi'
import { anonymizeFileStream, anonymizeTextStream } from '@/services/anonymizeStream'
import { statusApi } from '@/services/statusApi'
import {
  extractApiErrorMessage,
  extractPdfExportErrorMessage,
  isExpiredResultError,
} from '@/utils/errors'
import { DEFAULT_POLICY, policyDeviations } from '@/utils/policy'
import type {
  AnonymizeResponse,
  AnonymizedEntity,
  CustomRules,
  DetectorStatus,
  EntityType,
  ExternalEndpoint,
  Override,
  PdfPageRender,
  PolicyMap,
  RedactArea,
  StatusResponse,
  StreamProgressEvent,
  TransformationType,
} from '@/types/anonymizer'

export type SessionPhase = 'idle' | 'loading' | 'result'

export type DocumentStatus = 'queued' | 'processing' | 'done' | 'error'

/** The result panels a document can show (up to three at once). */
export type ResultPanelId = 'source' | 'pdf' | 'original' | 'anonymized'

/** Maximum simultaneous /anonymize/stream requests (browser connection budget). */
export const MAX_CONCURRENT_STREAMS = 5

/**
 * One document of the current batch. Owns EVERYTHING that is per-document:
 * source (file or pasted text), streaming progress, result, overrides,
 * selection, preview object URLs and the panel activation state — plus the
 * batch's policy/custom-rules snapshot captured once at submit. Memory only,
 * never persisted.
 */
export interface SessionDocument {
  id: string
  /** The ORIGINAL uploaded file (re-sent for PDF export). Null for pasted text. */
  file: File | null
  /** The pasted source text (start/retry of text runs). Null for file documents. */
  text: string | null
  name: string
  status: DocumentStatus
  /** Live progress of the fresh run; null before the first event (indeterminate). */
  progress: StreamProgressEvent | null
  /** Highest overall percent seen — kept as a max so the bar never dips. */
  progressMaxPercent: number
  /** True once any OCR event arrived (scanned PDF → OCR gets its own span). */
  progressSawOcr: boolean
  /** User-facing error message when `status` is 'error'. */
  error: string | null
  result: AnonymizeResponse | null
  /** Accumulated per-entity overrides, keyed by `${start}:${end}`. */
  overrides: Map<string, Override>
  selectedEntityIndex: number | null
  /** True while an override re-run is in flight (result view stays visible). */
  rerunning: boolean
  /** Redacted-PDF preview: object URL + backing blob (reused for downloads). */
  pdfPreviewUrl: string | null
  pdfPreviewBlob: Blob | null
  pdfPreviewLoading: boolean
  pdfPreviewError: string | null
  /** Bumped on every refresh/cleanup so stale in-flight responses are ignored. */
  pdfPreviewToken: number
  /** Object URL for the ORIGINAL uploaded PDF (lazy, "Original" panel). */
  originalPreviewUrl: string | null
  /** User-drawn blackout regions (PDF export only, normalized coordinates). */
  redactAreas: RedactArea[]
  /** Rendered pages for the area editor (lazy; data URLs, memory only). */
  pdfPages: PdfPageRender[] | null
  pdfPagesTruncated: boolean
  pdfPagesLoading: boolean
  pdfPagesError: string | null
  /** Active result panels in ACTIVATION order (restored on document switch). */
  activePanels: ResultPanelId[]
  /** Policy deviations captured at submit — used for ALL re-runs/exports. */
  policy: PolicyMap | null
  /** Custom rules captured at submit — used for ALL re-runs/exports. */
  rules: CustomRules | null
  /** Aborts the in-flight stream request on reset. */
  abort: AbortController | null
}

/** Stable identity of a detected entity across re-runs (offsets don't move). */
export function overrideKey(entity: { start: number; end: number }): string {
  return `${entity.start}:${entity.end}`
}

/**
 * Overall progress percent (0–100) of a document's run, or null while
 * indeterminate (no stream event yet).
 */
export function documentProgressPercent(doc: SessionDocument): number | null {
  return doc.progress === null ? null : doc.progressMaxPercent
}

/**
 * A document's contribution to the batch-overall percent: settled documents
 * (done OR error) count as 100, queued ones as 0, processing ones as their
 * monotonic stream percent.
 */
export function documentBatchPercent(doc: SessionDocument): number {
  if (doc.status === 'done' || doc.status === 'error') return 100
  if (doc.status === 'processing') return doc.progressMaxPercent
  return 0
}

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

/** True when the response was produced from a PDF (redactable source). */
function isPdfResult(response: AnonymizeResponse | null): boolean {
  return response?.source_type === 'pdf' || response?.source_type === 'pdf-ocr'
}

export const useSessionStore = defineStore('session', () => {
  const phase = ref<SessionPhase>('idle')

  /** The documents of the current batch, in submit order. */
  const documents = ref<SessionDocument[]>([])
  const activeDocumentId = ref<string | null>(null)

  /** The document whose panels/overrides/previews the result view shows. */
  const activeDocument = computed<SessionDocument | null>(
    () => documents.value.find((doc) => doc.id === activeDocumentId.value) ?? null,
  )

  /**
   * Bumped on reset so late completions/errors of aborted streams from a
   * previous batch can never touch the new batch's state.
   */
  let batchToken = 0
  let documentIdCounter = 0

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

  const status = ref<StatusResponse | null>(null)

  // ---------------------------------------------------------------------
  // Active-document views (existing component API, delegating to the entry)
  // ---------------------------------------------------------------------

  const result = computed<AnonymizeResponse | null>(() => activeDocument.value?.result ?? null)
  const sourceFile = computed<File | null>(() => activeDocument.value?.file ?? null)
  const selectedEntityIndex = computed<number | null>(
    () => activeDocument.value?.selectedEntityIndex ?? null,
  )
  const rerunning = computed(() => activeDocument.value?.rerunning ?? false)
  const overrides = computed<Map<string, Override>>(
    () => activeDocument.value?.overrides ?? new Map(),
  )
  const pdfPreviewUrl = computed(() => activeDocument.value?.pdfPreviewUrl ?? null)
  const pdfPreviewBlob = computed(() => activeDocument.value?.pdfPreviewBlob ?? null)
  const pdfPreviewLoading = computed(() => activeDocument.value?.pdfPreviewLoading ?? false)
  const pdfPreviewError = computed(() => activeDocument.value?.pdfPreviewError ?? null)
  const originalPreviewUrl = computed(() => activeDocument.value?.originalPreviewUrl ?? null)
  const activePanels = computed<ResultPanelId[]>(() => activeDocument.value?.activePanels ?? [])

  const selectedEntity = computed<AnonymizedEntity | null>(() => {
    const doc = activeDocument.value
    if (!doc || doc.result === null || doc.selectedEntityIndex === null) return null
    return doc.result.entities[doc.selectedEntityIndex] ?? null
  })

  /** Entity counts by type (active document), in a stable (first-seen) order. */
  const entityCounts = computed<{ type: EntityType; count: number }[]>(() => {
    const entities = result.value?.entities
    if (!entities) return []
    const counts = new Map<EntityType, number>()
    for (const entity of entities) {
      counts.set(entity.entity_type, (counts.get(entity.entity_type) ?? 0) + 1)
    }
    return [...counts.entries()].map(([type, count]) => ({ type, count }))
  })

  /**
   * The document featured on the landing progress card while the batch runs:
   * the first still-streaming one (all start concurrently up to the cap).
   */
  const loadingDocument = computed<SessionDocument | null>(
    () =>
      documents.value.find((doc) => doc.status === 'processing') ??
      documents.value.find((doc) => doc.status === 'queued') ??
      documents.value[0] ??
      null,
  )

  /** Settled documents of the batch (done OR error = "abgeschlossen"). */
  const batchSettledCount = computed(
    () => documents.value.filter((doc) => doc.status === 'done' || doc.status === 'error').length,
  )

  /** Failed documents of the batch. */
  const batchFailedCount = computed(
    () => documents.value.filter((doc) => doc.status === 'error').length,
  )

  /**
   * Floor keeping the batch-overall percent monotonically non-decreasing (a
   * retry resets one document's contribution to 0). Reset with the batch.
   */
  const batchPercentFloor = ref(0)

  /**
   * Overall batch progress (0–100): mean over ALL documents where each
   * contributes its monotonic percent (queued = 0, settled = 100). Never
   * decreases within a batch.
   */
  const batchOverallPercent = computed(() => {
    const docs = documents.value
    if (docs.length === 0) return 0
    const mean = docs.reduce((sum, doc) => sum + documentBatchPercent(doc), 0) / docs.length
    return Math.max(mean, batchPercentFloor.value)
  })

  watch(batchOverallPercent, (value) => {
    if (value > batchPercentFloor.value) batchPercentFloor.value = value
  })

  // ---------------------------------------------------------------------
  // Status endpoint / banners
  // ---------------------------------------------------------------------

  /** External (non-local) endpoints that document content is sent to. */
  const externalEndpoints = computed<ExternalEndpoint[]>(
    () => status.value?.external_endpoints.filter((endpoint) => !endpoint.local) ?? [],
  )

  /** Detectors that are enabled but not ready (e.g. LLM not configured). */
  const notReadyDetectors = computed<DetectorStatus[]>(
    () => status.value?.detectors.filter((detector) => detector.enabled && !detector.ready) ?? [],
  )

  async function fetchStatus(): Promise<void> {
    try {
      status.value = (await statusApi.getStatus()).data
    } catch {
      // Backend not reachable yet — errors surface on submit instead.
      status.value = null
    }
  }

  // ---------------------------------------------------------------------
  // Advanced settings (landing page)
  // ---------------------------------------------------------------------

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

  // ---------------------------------------------------------------------
  // Batch lifecycle: submit → queue → parallel streams → result phase
  // ---------------------------------------------------------------------

  function createDocument(
    input: { file: File | null; text: string | null; name: string },
    batchPolicy: PolicyMap | null,
    batchRules: CustomRules | null,
  ): SessionDocument {
    const doc: SessionDocument = {
      id: `doc-${++documentIdCounter}`,
      file: input.file,
      text: input.text,
      name: input.name,
      status: 'queued',
      progress: null,
      progressMaxPercent: 0,
      progressSawOcr: false,
      error: null,
      result: null,
      overrides: new Map(),
      selectedEntityIndex: null,
      rerunning: false,
      pdfPreviewUrl: null,
      pdfPreviewBlob: null,
      pdfPreviewLoading: false,
      pdfPreviewError: null,
      pdfPreviewToken: 0,
      originalPreviewUrl: null,
      redactAreas: [],
      pdfPages: null,
      pdfPagesTruncated: false,
      pdfPagesLoading: false,
      pdfPagesError: null,
      activePanels: ['source'],
      policy: batchPolicy,
      rules: batchRules,
      abort: null,
    }
    // reactive() up front: the queue/stream callbacks hold direct references,
    // which must be the SAME proxy the components see through `documents`.
    return reactive(doc)
  }

  function startBatch(inputs: { file: File | null; text: string | null; name: string }[]): void {
    if (inputs.length === 0) return
    // Defensive: a previous batch (should already be reset) is fully dropped.
    reset()
    // Policy/custom rules are captured ONCE at submit for the whole batch.
    const batchPolicy = policyOverrides.value
    const batchRules = customRules.value
    documents.value = inputs.map((input) => createDocument(input, batchPolicy, batchRules))
    activeDocumentId.value = documents.value[0]!.id
    phase.value = 'loading'
    pumpQueue()
  }

  /**
   * Anonymize dropped/picked files: one document per file, ALL processed
   * concurrently (capped at MAX_CONCURRENT_STREAMS; the rest queue up).
   * Errors surface per document in the result view — this never rejects.
   */
  function submitFiles(files: File[]): void {
    startBatch(files.map((file) => ({ file, text: null, name: file.name })))
  }

  /** Anonymize pasted text — always a single-document batch. */
  function submitText(text: string): void {
    startBatch([{ file: null, text, name: 'Eingefügter Text' }])
  }

  /** Start queued documents while free stream slots exist. */
  function pumpQueue(): void {
    const token = batchToken
    for (const doc of documents.value) {
      if (doc.status !== 'queued') continue
      const processing = documents.value.filter((d) => d.status === 'processing').length
      if (processing >= MAX_CONCURRENT_STREAMS) return
      void processDocument(doc, token)
    }
  }

  /** onProgress callback of one document's stream. */
  function onDocumentProgress(doc: SessionDocument, event: StreamProgressEvent): void {
    if (event.stage === 'ocr') doc.progressSawOcr = true
    doc.progress = event
    const [base, span] = stageSpan(event.stage, doc.progressSawOcr)
    const fraction = Math.min(event.done / Math.max(event.total, 1), 1)
    doc.progressMaxPercent = Math.min(Math.max(doc.progressMaxPercent, base + span * fraction), 100)
  }

  /**
   * Run ONE document through /anonymize/stream. Failures are isolated: they
   * mark only this document as 'error' and never affect the others.
   */
  async function processDocument(doc: SessionDocument, token: number): Promise<void> {
    doc.status = 'processing'
    doc.error = null
    doc.progress = null
    doc.progressMaxPercent = 0
    doc.progressSawOcr = false
    const abort = new AbortController()
    doc.abort = abort
    const onProgress = (event: StreamProgressEvent) => {
      if (token === batchToken) onDocumentProgress(doc, event)
    }
    try {
      const response = doc.file
        ? await anonymizeFileStream(doc.file, doc.policy, doc.rules, onProgress, abort.signal)
        : await anonymizeTextStream(doc.text ?? '', doc.policy, doc.rules, onProgress, abort.signal)
      if (token !== batchToken) return // batch was reset while streaming
      doc.result = response
      doc.overrides = new Map()
      doc.selectedEntityIndex = null
      // Default panel selection: source review + result side by side (the
      // result is the redacted PDF for PDF sources, the text otherwise).
      doc.activePanels = isPdfResult(response) ? ['source', 'pdf'] : ['source', 'anonymized']
      doc.status = 'done'
      maybeAdvancePhase(doc)
      // For PDF sources, load the redacted-PDF preview right away (not
      // awaited — the text result is already usable while it renders).
      void refreshPdfPreviewFor(doc)
    } catch (err) {
      if (token !== batchToken) return
      doc.status = 'error'
      doc.error = extractApiErrorMessage(err)
      maybeAdvancePhase(doc)
    } finally {
      if (token === batchToken) {
        doc.abort = null
        doc.progress = null
        pumpQueue() // a slot freed up — start the next queued document
      }
    }
  }

  /**
   * Leave the landing view as soon as the FIRST document finishes
   * successfully (that one becomes active; the rest keep processing in the
   * background). If ALL documents settle without a single success, the result
   * view still opens so the per-document error cards (with retry) are shown.
   */
  function maybeAdvancePhase(settled: SessionDocument): void {
    if (phase.value !== 'loading') return
    if (settled.status === 'done') {
      activeDocumentId.value = settled.id
      phase.value = 'result'
      return
    }
    const allSettled = documents.value.every(
      (doc) => doc.status === 'done' || doc.status === 'error',
    )
    if (allSettled) phase.value = 'result'
  }

  /** Switch the active document (also while others are still processing). */
  function selectDocument(id: string): void {
    if (documents.value.some((doc) => doc.id === id)) activeDocumentId.value = id
  }

  /** Re-run ONE errored document (keeps its batch policy/rules snapshot). */
  function retryDocument(id: string): void {
    const doc = documents.value.find((entry) => entry.id === id)
    if (!doc || doc.status !== 'error') return
    doc.status = 'queued'
    doc.error = null
    pumpQueue()
  }

  /** Abort any in-flight work and revoke this document's object URLs. */
  function cleanupDocument(doc: SessionDocument): void {
    doc.abort?.abort()
    doc.abort = null
    doc.pdfPreviewToken += 1 // ignore any in-flight preview response
    if (doc.pdfPreviewUrl !== null) URL.revokeObjectURL(doc.pdfPreviewUrl)
    doc.pdfPreviewUrl = null
    doc.pdfPreviewBlob = null
    doc.pdfPreviewLoading = false
    doc.pdfPreviewError = null
    if (doc.originalPreviewUrl !== null) URL.revokeObjectURL(doc.originalPreviewUrl)
    doc.originalPreviewUrl = null
    // Rendered pages are data URLs (no revoke needed) — just drop the memory.
    doc.pdfPages = null
    doc.pdfPagesLoading = false
    doc.pdfPagesError = null
  }

  /** Remove one document from the batch (revoking its object URLs). */
  function removeDocument(id: string): void {
    const index = documents.value.findIndex((doc) => doc.id === id)
    if (index === -1) return
    const [doc] = documents.value.splice(index, 1)
    cleanupDocument(doc!)
    if (activeDocumentId.value === id) {
      const neighbor = documents.value[Math.min(index, documents.value.length - 1)]
      activeDocumentId.value = neighbor?.id ?? null
    }
    if (documents.value.length === 0) phase.value = 'idle'
  }

  /**
   * Drop the whole batch and return to the input screen: abort in-flight
   * streams, revoke ALL object URLs, clear every document.
   */
  function reset(): void {
    batchToken += 1
    for (const doc of documents.value) cleanupDocument(doc)
    documents.value = []
    activeDocumentId.value = null
    batchPercentFloor.value = 0
    phase.value = 'idle'
  }

  // ---------------------------------------------------------------------
  // Result panels (per document, restored on switch)
  // ---------------------------------------------------------------------

  /** Activate a result panel on the ACTIVE document (max 3, oldest evicted). */
  function activatePanel(id: ResultPanelId): void {
    const doc = activeDocument.value
    if (!doc || doc.activePanels.includes(id)) return
    // The original-PDF object URL is created lazily on first activation.
    if (id === 'original') ensureOriginalPreviewUrl()
    doc.activePanels.push(id)
    if (doc.activePanels.length > 3) doc.activePanels.shift()
  }

  /** Toggle a result panel on the ACTIVE document (at least one stays on). */
  function togglePanel(id: ResultPanelId): void {
    const doc = activeDocument.value
    if (!doc) return
    const index = doc.activePanels.indexOf(id)
    if (index === -1) {
      activatePanel(id)
      return
    }
    if (doc.activePanels.length === 1) return
    doc.activePanels.splice(index, 1)
  }

  // ---------------------------------------------------------------------
  // Previews (per document; public actions target the ACTIVE document)
  // ---------------------------------------------------------------------

  /**
   * Lazily create the object URL for the ACTIVE document's ORIGINAL uploaded
   * PDF (used by the "Original" panel for PDF sources). Returns null when the
   * original file is gone or the result is not a PDF.
   */
  function ensureOriginalPreviewUrl(): string | null {
    const doc = activeDocument.value
    if (!doc) return null
    if (doc.originalPreviewUrl !== null) return doc.originalPreviewUrl
    if (doc.file === null || !isPdfResult(doc.result)) return null
    doc.originalPreviewUrl = URL.createObjectURL(doc.file)
    return doc.originalPreviewUrl
  }

  /**
   * (Re-)export the redacted PDF for ONE document with all its accumulated
   * overrides and show it as an inline preview. No-op for non-PDF results or
   * when the original file is gone. Called automatically after a successful
   * PDF run and after every successful override re-run, so the preview always
   * reflects the user's overrides. Can take up to a minute for scans on a
   * backend cache miss (hence the dedicated loading state).
   */
  async function refreshPdfPreviewFor(doc: SessionDocument): Promise<void> {
    const current = doc.result
    const file = doc.file
    if (current === null || file === null || !isPdfResult(current)) return

    const token = ++doc.pdfPreviewToken
    doc.pdfPreviewLoading = true
    doc.pdfPreviewError = null
    try {
      const { data } = await anonymizeApi.exportPdf(
        file,
        current.request_id,
        [...doc.overrides.values()],
        doc.policy,
        doc.rules,
        doc.redactAreas,
      )
      if (token !== doc.pdfPreviewToken) return
      if (doc.pdfPreviewUrl !== null) URL.revokeObjectURL(doc.pdfPreviewUrl)
      doc.pdfPreviewBlob = data
      doc.pdfPreviewUrl = URL.createObjectURL(data)
    } catch (err) {
      if (token !== doc.pdfPreviewToken) return
      doc.pdfPreviewError = await extractPdfExportErrorMessage(err)
    } finally {
      if (token === doc.pdfPreviewToken) doc.pdfPreviewLoading = false
    }
  }

  /** Refresh the ACTIVE document's redacted-PDF preview. */
  async function refreshPdfPreview(): Promise<void> {
    const doc = activeDocument.value
    if (doc) await refreshPdfPreviewFor(doc)
  }

  // ---------------------------------------------------------------------
  // Area redaction (user-drawn blackout regions; PDF export only)
  // ---------------------------------------------------------------------

  const redactAreas = computed<RedactArea[]>(() => activeDocument.value?.redactAreas ?? [])
  const pdfPages = computed<PdfPageRender[] | null>(() => activeDocument.value?.pdfPages ?? null)
  const pdfPagesTruncated = computed(() => activeDocument.value?.pdfPagesTruncated ?? false)
  const pdfPagesLoading = computed(() => activeDocument.value?.pdfPagesLoading ?? false)
  const pdfPagesError = computed(() => activeDocument.value?.pdfPagesError ?? null)

  /** Lazily render the ACTIVE document's pages for the area editor. */
  async function loadPdfPages(): Promise<void> {
    const doc = activeDocument.value
    if (!doc || doc.file === null || doc.pdfPages !== null || doc.pdfPagesLoading) return
    doc.pdfPagesLoading = true
    doc.pdfPagesError = null
    try {
      const { data } = await anonymizeApi.renderPdfPages(doc.file)
      doc.pdfPages = data.pages
      doc.pdfPagesTruncated = data.truncated
    } catch (err) {
      doc.pdfPagesError = extractApiErrorMessage(err)
    } finally {
      doc.pdfPagesLoading = false
    }
  }

  /** Add one drawn area and refresh the redacted-PDF preview. */
  function addRedactArea(area: RedactArea): void {
    const doc = activeDocument.value
    if (!doc) return
    doc.redactAreas.push(area)
    void refreshPdfPreviewFor(doc)
  }

  /** Remove one area (by index) and refresh the redacted-PDF preview. */
  function removeRedactArea(index: number): void {
    const doc = activeDocument.value
    if (!doc || index < 0 || index >= doc.redactAreas.length) return
    doc.redactAreas.splice(index, 1)
    void refreshPdfPreviewFor(doc)
  }

  /**
   * Add every embedded-image bounding box as an area ("Alle Bilder
   * schwärzen"). Boxes that were already added are skipped; returns the
   * number of NEW areas.
   */
  function addImageAreas(): number {
    const doc = activeDocument.value
    if (!doc || doc.pdfPages === null) return 0
    let added = 0
    for (const page of doc.pdfPages) {
      for (const box of page.image_boxes) {
        const exists = doc.redactAreas.some(
          (area) =>
            area.page === page.page &&
            Math.abs(area.x0 - box.x0) < 1 &&
            Math.abs(area.y0 - box.y0) < 1 &&
            Math.abs(area.x1 - box.x1) < 1 &&
            Math.abs(area.y1 - box.y1) < 1,
        )
        if (exists) continue
        doc.redactAreas.push({ page: page.page, ...box })
        added += 1
      }
    }
    if (added > 0) void refreshPdfPreviewFor(doc)
    return added
  }

  // ---------------------------------------------------------------------
  // Overrides / re-runs (per document; public actions target the ACTIVE one)
  // ---------------------------------------------------------------------

  function indexOfEntityKey(entities: AnonymizedEntity[], key: string): number | null {
    const index = entities.findIndex((entity) => overrideKey(entity) === key)
    return index === -1 ? null : index
  }

  /**
   * Re-run ONE document with all its accumulated overrides. Tries the cheap
   * cached path first ({request_id, overrides}); on 410 (cache expired) it
   * automatically retries ONCE with the full source text plus the same
   * overrides and adopts the new request_id. Always uses the document's OWN
   * request_id, overrides and batch policy/rules — never another document's.
   * The result view stays visible (`rerunning` instead of `phase`); on
   * failure the override map is rolled back and the error rethrown (caller
   * shows a toast).
   */
  async function rerunOverridesFor(
    doc: SessionDocument,
    previousOverrides: Map<string, Override>,
  ): Promise<void> {
    if (!doc.result) return
    const requestId = doc.result.request_id
    const sourceText = doc.result.source_text
    const allOverrides = [...doc.overrides.values()]
    const selected =
      doc.selectedEntityIndex === null
        ? null
        : (doc.result.entities[doc.selectedEntityIndex] ?? null)
    const selectedKey = selected === null ? null : overrideKey(selected)

    doc.rerunning = true
    try {
      let response: AnonymizeResponse
      try {
        // Cached path: only preserve_terms may be sent — redact terms and the
        // custom instruction are already baked into the cached detection.
        response = (
          await anonymizeApi.rerunWithOverrides(
            requestId,
            allOverrides,
            doc.policy,
            doc.rules?.preserveTerms ?? null,
          )
        ).data
      } catch (err) {
        if (!isExpiredResultError(err)) throw err
        // Cache expired — re-detect from the original text with the same
        // overrides (full custom rules apply again); the response carries a
        // fresh request_id.
        response = (
          await anonymizeApi.anonymizeText(sourceText, allOverrides, doc.policy, doc.rules)
        ).data
      }
      doc.result = response
      // Re-select the same entity by offsets (indices may shift on re-runs).
      doc.selectedEntityIndex =
        selectedKey === null ? null : indexOfEntityKey(response.entities, selectedKey)
      // The preview must reflect the new overrides (no-op for non-PDF results).
      void refreshPdfPreviewFor(doc)
    } catch (err) {
      doc.overrides = previousOverrides
      throw err
    } finally {
      doc.rerunning = false
    }
  }

  /** Re-run the ACTIVE document with its accumulated overrides. */
  async function rerunOverrides(previousOverrides: Map<string, Override>): Promise<void> {
    const doc = activeDocument.value
    if (doc) await rerunOverridesFor(doc, previousOverrides)
  }

  /** The ACTIVE document's pending override for an entity, if any. */
  function overrideFor(entity: { start: number; end: number }): Override | undefined {
    return activeDocument.value?.overrides.get(overrideKey(entity))
  }

  /**
   * Set (or merge) an override for one entity of the ACTIVE document and
   * immediately re-run it. A type change intentionally drops any
   * transformation override so the default policy for the new type applies.
   */
  function applyEntityOverride(
    entity: AnonymizedEntity,
    patch: { transformation?: TransformationType; entity_type?: EntityType },
  ): Promise<void> {
    const doc = activeDocument.value
    if (!doc) return Promise.resolve()
    const key = overrideKey(entity)
    const previous = new Map(doc.overrides)
    const existing = doc.overrides.get(key)
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
    doc.overrides.set(key, next)
    return rerunOverridesFor(doc, previous)
  }

  /**
   * Manually redact an arbitrary text region of the ACTIVE document (mouse
   * selection in the source review). The offsets are Unicode CODE POINTS into
   * `source_text`; because they don't match a detected entity, the backend
   * turns the override into a user-defined span (detector `user_manual`,
   * `metadata.user_manual`) on the re-run. Removing the override again
   * (resetEntityOverride) undoes it.
   */
  function addManualRedaction(start: number, end: number): Promise<void> {
    const doc = activeDocument.value
    if (!doc || !doc.result) return Promise.resolve()
    const previous = new Map(doc.overrides)
    const text = Array.from(doc.result.source_text).slice(start, end).join('')
    doc.overrides.set(overrideKey({ start, end }), { start, end, text, transformation: 'REMOVE' })
    return rerunOverridesFor(doc, previous)
  }

  /** Remove any override for this entity and re-run with the remaining ones. */
  function resetEntityOverride(entity: AnonymizedEntity): Promise<void> {
    const doc = activeDocument.value
    if (!doc) return Promise.resolve()
    const key = overrideKey(entity)
    const previous = new Map(doc.overrides)
    if (!doc.overrides.delete(key)) return Promise.resolve()
    return rerunOverridesFor(doc, previous)
  }

  function selectEntity(index: number | null): void {
    const doc = activeDocument.value
    if (doc) doc.selectedEntityIndex = index
  }

  return {
    phase,
    documents,
    activeDocumentId,
    activeDocument,
    loadingDocument,
    batchSettledCount,
    batchFailedCount,
    batchOverallPercent,
    selectDocument,
    retryDocument,
    removeDocument,
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
    activePanels,
    activatePanel,
    togglePanel,
    pdfPreviewUrl,
    pdfPreviewBlob,
    pdfPreviewLoading,
    pdfPreviewError,
    refreshPdfPreview,
    originalPreviewUrl,
    ensureOriginalPreviewUrl,
    redactAreas,
    pdfPages,
    pdfPagesTruncated,
    pdfPagesLoading,
    pdfPagesError,
    loadPdfPages,
    addRedactArea,
    removeRedactArea,
    addImageAreas,
    status,
    externalEndpoints,
    notReadyDetectors,
    fetchStatus,
    submitText,
    submitFiles,
    selectEntity,
    overrideFor,
    applyEntityOverride,
    addManualRedaction,
    resetEntityOverride,
    rerunOverrides,
    reset,
  }
})
