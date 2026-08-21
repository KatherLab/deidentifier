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
import { i18n, t, type SupportedLocale } from '@/i18n'
import { loadLocaleMessages } from '@/composables/useLocale'
import { anonymizeApi } from '@/services/anonymizeApi'
import { anonymizeFileStream, anonymizeTextStream } from '@/services/anonymizeStream'
import { statusApi } from '@/services/statusApi'
import {
  extractApiErrorMessage,
  extractPdfExportErrorMessage,
  isExpiredResultError,
} from '@/utils/errors'
import { DEFAULT_POLICY, policyDeviations } from '@/utils/policy'
import { formatRemaining, remainingSeconds } from '@/utils/lifetime'
import { findMatches, type MatchRange } from '@/utils/textSegments'
import { useToast } from '@/composables/useToast'
import { useSettingsStore } from '@/stores/settings'
import type {
  AnonymizeResponse,
  AnonymizedEntity,
  Banner,
  CacheLifetime,
  CustomRules,
  DetectorStatus,
  EntityType,
  ExternalEndpoint,
  Override,
  OutputLanguage,
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
  /**
   * The selected entities as override keys, in CLICK order — the last one is
   * the focus (detail panel, scroll-into-view). Keys and not indices, because
   * indices shift on every override re-run while offsets never move.
   */
  selectedKeys: string[]
  /** Origin of shift-click range selection: the last plain or toggling click. */
  selectionAnchorKey: string | null
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
  /**
   * The pages of the REDACTED preview PDF. Rendered from `pdfPreviewBlob`,
   * which the store already holds, so this costs one page render and no
   * detection. The area editor's optional background for a native PDF — and
   * its ONLY drawing surface for a scanned one, whose export is a
   * reconstruction on a different page geometry than the scan.
   */
  pdfRedactedPages: PdfPageRender[] | null
  pdfRedactedPagesTruncated: boolean
  /**
   * The preview blob `pdfRedactedPages` was rendered from (identity, not a
   * copy). Every override or drawn area produces a NEW blob, which is what
   * makes these pages stale — the old ones stay on screen until the new
   * render arrives, so the view never flickers back to un-redacted pages.
   */
  pdfRedactedPagesSource: Blob | null
  pdfRedactedPagesLoading: boolean
  pdfRedactedPagesError: string | null
  /** Bumped per render so a superseded in-flight response is ignored. */
  pdfRedactedPagesToken: number
  /**
   * Whether the area editor draws on the redacted pages. Defaults to true:
   * the point of the editor is to add what the detectors missed, which means
   * seeing what they already caught. Turning it off shows the originals.
   */
  areasShowRedacted: boolean
  /** Active result panels in ACTIVATION order (restored on document switch). */
  activePanels: ResultPanelId[]
  /**
   * The panel the reviewer last worked in. Ctrl/Cmd+F searches THIS one — the
   * final check ("is that name really gone?") is always about one specific
   * view, and asking which would be one question too many.
   */
  focusedPanel: ResultPanelId | null
  /** The panel whose search bar is open, or null while none is. */
  searchPanel: ResultPanelId | null
  /** The search term. Memory only — never persisted, like every other input. */
  searchQuery: string
  /** Which hit the reviewer is on (clamped to the hit count when read). */
  searchMatchIndex: number
  /** Policy deviations captured at submit — used for ALL re-runs/exports. */
  policy: PolicyMap | null
  /** Custom rules captured at submit — used for ALL re-runs/exports. */
  rules: CustomRules | null
  /** Force-OCR flag captured at submit — re-sent on export (cache-miss parity). */
  forceOcr: boolean
  /** OCR profile captured at submit; null = server default. Re-sent on export. */
  ocrProfile: string | null
  /**
   * Language of the placeholders written into THIS document, captured at
   * submit and re-sent with every re-run/export. Switching the interface
   * language while reviewing never rewrites a finished document.
   */
  outputLanguage: OutputLanguage
  /**
   * When the backend's cached detection for this document expires, as an
   * absolute client clock time (epoch ms) derived from the `expires_in_seconds`
   * the server reported. Absolute, so the countdown survives a tab the OS
   * suspended; null before the first result.
   */
  expiresAt: number | null
  /** False once the entry hit its hard lifetime ceiling — no more extending. */
  canExtend: boolean
  /** True while an extension request is in flight. */
  extending: boolean
  /** Aborts the in-flight stream request on reset. */
  abort: AbortController | null
}

/** Stable identity of a detected entity across re-runs (offsets don't move). */
export function overrideKey(entity: { start: number; end: number }): string {
  return `${entity.start}:${entity.end}`
}

/**
 * What a bulk action does to every selected entity.
 *
 * `preserve` is asymmetric on purpose: a DETECTED entity is released with a
 * PRESERVE override, while a manually redacted span (`user_manual`) has no
 * detection behind it — releasing it means dropping the override that created
 * it. `EntityDetailPanel` makes the same distinction for a single entity.
 */
export type SelectionAction = 'redact' | 'preserve' | 'reset'

/**
 * Comparison form for "all occurrences of this text": whitespace-collapsed,
 * case-folded — the same normalization the backend applies to preserve terms
 * and consistent tags (`utils/transformation.py::_normalize`).
 */
function normalizeEntityText(value: string): string {
  return value.replace(/\s+/gu, ' ').trim().toLowerCase()
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

  /**
   * Force OCR (advanced settings). Skips the embedded-text probe so every page
   * of an uploaded PDF is re-OCR'd — for scans whose text layer is missing or
   * garbage. Only meaningful for PDF uploads; ignored for text/DOCX. Captured
   * at submit (fresh-run only, like redactTerms) and re-sent on export so a
   * cache-miss re-extraction matches.
   */
  const forceOcr = ref(false)

  /**
   * Which of the server's OCR profiles the next run uses (advanced settings;
   * only offered when the backend configures several). `null` = the server's
   * default profile. Captured at submit like forceOcr and re-sent on export
   * so a cache-miss re-extraction runs the same OCR model.
   */
  const ocrProfile = ref<string | null>(null)

  /**
   * Language of the placeholders in the anonymized output (advanced settings).
   * `null` means "follow the interface language", which is what most users
   * want; picking one explicitly pins it. Memory only — never persisted, like
   * every other per-run setting.
   */
  const outputLanguageOverride = ref<OutputLanguage | null>(null)

  /** The language the NEXT run will write its placeholders in. */
  const outputLanguage = computed<OutputLanguage>(
    () => outputLanguageOverride.value ?? (i18n.global.locale.value as SupportedLocale),
  )

  /** Pin (or release, with `null`) the output language of the next run. */
  function setOutputLanguage(language: OutputLanguage | null): void {
    outputLanguageOverride.value = language
    // The policy editor previews that language's placeholders, so make sure
    // its catalog is in memory (no-op for an already-loaded locale).
    if (language) void loadLocaleMessages(language)
  }

  const status = ref<StatusResponse | null>(null)

  // ---------------------------------------------------------------------
  // Active-document views (existing component API, delegating to the entry)
  // ---------------------------------------------------------------------

  const result = computed<AnonymizeResponse | null>(() => activeDocument.value?.result ?? null)
  const sourceFile = computed<File | null>(() => activeDocument.value?.file ?? null)
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

  /**
   * Indices of every selected entity in the active result, in DOCUMENT order
   * (the response is already ordered by offset). Keys that no longer resolve —
   * a manual span whose override a re-run dropped — simply fall out.
   */
  const selectedEntityIndices = computed<number[]>(() => {
    const doc = activeDocument.value
    if (!doc || doc.result === null || doc.selectedKeys.length === 0) return []
    const keys = new Set(doc.selectedKeys)
    const indices: number[] = []
    doc.result.entities.forEach((entity, index) => {
      if (keys.has(overrideKey(entity))) indices.push(index)
    })
    return indices
  })

  /** The selected entities themselves, in document order. */
  const selectedEntities = computed<AnonymizedEntity[]>(() => {
    const entities = result.value?.entities
    if (!entities) return []
    return selectedEntityIndices.value.map((index) => entities[index]!)
  })

  /**
   * The entity the source view scrolls to and badges: the last one the user
   * touched, whatever else is selected alongside it.
   */
  const selectedEntityIndex = computed<number | null>(() => {
    const doc = activeDocument.value
    if (!doc || doc.result === null) return null
    const focus = doc.selectedKeys[doc.selectedKeys.length - 1]
    if (focus === undefined) return null
    return indexOfEntityKey(doc.result.entities, focus)
  })

  /**
   * The ONE selected entity, or null while zero or several are selected — the
   * detail panel handles exactly one entity, `EntitySelectionBar` the rest.
   */
  const selectedEntity = computed<AnonymizedEntity | null>(() =>
    selectedEntities.value.length === 1 ? selectedEntities.value[0]! : null,
  )

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

  /** Deployment-wide banner configured by the operator (null when disabled). */
  const banner = computed<Banner | null>(() => status.value?.banner ?? null)

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

  /**
   * True when policy OR custom rules OR force-OCR OR the output language
   * deviate from the defaults. An output language that matches the interface
   * is not a deviation — it is what would have happened anyway.
   */
  const advancedCustomized = computed(
    () =>
      policyCustomized.value ||
      customRules.value !== null ||
      forceOcr.value ||
      ocrProfile.value !== null ||
      (outputLanguageOverride.value !== null &&
        outputLanguageOverride.value !== i18n.global.locale.value),
  )

  function setPolicyTransformation(type: EntityType, transformation: TransformationType): void {
    policy.value = { ...policy.value, [type]: transformation }
  }

  /** Reset ALL advanced settings: policy AND custom rules ("Zurücksetzen"). */
  function resetAdvancedSettings(): void {
    policy.value = { ...DEFAULT_POLICY }
    customInstruction.value = ''
    redactTerms.value = []
    preserveTerms.value = []
    forceOcr.value = false
    ocrProfile.value = null
    outputLanguageOverride.value = null
  }

  // ---------------------------------------------------------------------
  // Batch lifecycle: submit → queue → parallel streams → result phase
  // ---------------------------------------------------------------------

  function createDocument(
    input: { file: File | null; text: string | null; name: string },
    batchPolicy: PolicyMap | null,
    batchRules: CustomRules | null,
    batchForceOcr: boolean,
    batchOcrProfile: string | null,
    batchOutputLanguage: OutputLanguage,
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
      selectedKeys: [],
      selectionAnchorKey: null,
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
      pdfRedactedPages: null,
      pdfRedactedPagesTruncated: false,
      pdfRedactedPagesSource: null,
      pdfRedactedPagesLoading: false,
      pdfRedactedPagesError: null,
      pdfRedactedPagesToken: 0,
      areasShowRedacted: true,
      activePanels: ['source'],
      focusedPanel: null,
      searchPanel: null,
      searchQuery: '',
      searchMatchIndex: 0,
      policy: batchPolicy,
      rules: batchRules,
      forceOcr: batchForceOcr,
      ocrProfile: batchOcrProfile,
      outputLanguage: batchOutputLanguage,
      expiresAt: null,
      canExtend: false,
      extending: false,
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
    // Policy/custom rules/force-OCR/output language are captured ONCE at
    // submit for the batch.
    const batchPolicy = policyOverrides.value
    const batchRules = customRules.value
    const batchForceOcr = forceOcr.value
    const batchOcrProfile = ocrProfile.value
    const batchOutputLanguage = outputLanguage.value
    documents.value = inputs.map((input) =>
      createDocument(
        input,
        batchPolicy,
        batchRules,
        batchForceOcr,
        batchOcrProfile,
        batchOutputLanguage,
      ),
    )
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
    startBatch([{ file: null, text, name: t('input.pasted_text') }])
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
        ? await anonymizeFileStream(
            doc.file,
            doc.policy,
            doc.rules,
            doc.forceOcr,
            doc.ocrProfile,
            doc.outputLanguage,
            onProgress,
            abort.signal,
          )
        : await anonymizeTextStream(
            doc.text ?? '',
            doc.policy,
            doc.rules,
            doc.outputLanguage,
            onProgress,
            abort.signal,
          )
      if (token !== batchToken) return // batch was reset while streaming
      doc.result = response
      adoptLifetime(doc, response.lifetime)
      doc.overrides = new Map()
      doc.selectedKeys = []
      doc.selectionAnchorKey = null
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

  /**
   * Abort any in-flight work, revoke this document's object URLs, and tell the
   * backend to forget its cached detection now rather than at the end of the
   * TTL — the document is going away here, so the server-side copy should too.
   */
  function cleanupDocument(doc: SessionDocument): void {
    doc.abort?.abort()
    doc.abort = null
    if (doc.result !== null) void anonymizeApi.forgetResult(doc.result.request_id)
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
    doc.pdfRedactedPagesToken += 1 // ignore any in-flight page render
    doc.pdfRedactedPages = null
    doc.pdfRedactedPagesTruncated = false
    doc.pdfRedactedPagesSource = null
    doc.pdfRedactedPagesLoading = false
    doc.pdfRedactedPagesError = null
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

  // ---------------------------------------------------------------------
  // Result lifetime (the backend holds the detection for a bounded window)
  // ---------------------------------------------------------------------

  /**
   * When the FIRST of the batch's results expires. The whole batch is treated
   * as one lifetime: the documents were submitted together, they expire within
   * seconds of each other, and a reviewer asking "how long do I have?" means
   * their work, not one tab of it. Null while nothing has finished.
   */
  const resultsExpireAt = computed<number | null>(() => {
    const deadlines = documents.value
      .filter((doc) => doc.result !== null && doc.expiresAt !== null)
      .map((doc) => doc.expiresAt as number)
    return deadlines.length === 0 ? null : Math.min(...deadlines)
  })

  /** True while any result still has headroom below its lifetime ceiling. */
  const resultsCanExtend = computed(() =>
    documents.value.some((doc) => doc.result !== null && doc.canExtend),
  )

  /** True while an extension is in flight (the buttons show a spinner). */
  const extendingResults = computed(() => documents.value.some((doc) => doc.extending))

  /**
   * Turn the server's "expires in N seconds" into an absolute deadline on the
   * client clock. Absolute so the countdown stays right across a suspended tab;
   * derived from a duration so the two clocks never have to agree.
   */
  function adoptLifetime(doc: SessionDocument, lifetime: CacheLifetime): void {
    doc.expiresAt = Date.now() + lifetime.expires_in_seconds * 1000
    doc.canExtend = lifetime.can_extend
  }

  /** Mark a document's server-side copy as gone (410, or the clock ran out). */
  function markExpired(doc: SessionDocument): void {
    doc.expiresAt = Date.now()
    doc.canExtend = false
  }

  /**
   * Keep the batch's results alive for another window.
   *
   * Extends EVERY document that still has one, not just the active one: the
   * documents of a batch expire within seconds of each other, and a reviewer
   * who asks for more time means the work in front of them, not one tab of it.
   * A document the backend has already forgotten is marked expired rather than
   * retried — the next edit re-sends its source text anyway.
   *
   * Always confirms the outcome with a toast. Someone who extends before
   * leaving their desk needs to know it worked, and needs to be told when the
   * hard ceiling means it did not.
   */
  async function extendResults(): Promise<void> {
    const live = documents.value.filter((doc) => doc.result !== null && !doc.extending)
    if (live.length === 0) return
    for (const doc of live) doc.extending = true
    try {
      await Promise.all(
        live.map(async (doc) => {
          try {
            const { data } = await anonymizeApi.extendResult(doc.result!.request_id)
            adoptLifetime(doc, data)
          } catch {
            markExpired(doc)
          }
        }),
      )
    } finally {
      for (const doc of live) doc.extending = false
    }

    const toast = useToast()
    const left = remainingSeconds(resultsExpireAt.value, Date.now())
    const time = formatRemaining(left)
    if (left === null || left === 0) {
      toast.error(t('result.lifetime.expired_hint'))
    } else if (!resultsCanExtend.value) {
      toast.info(t('result.lifetime.extended_at_maximum', { time }))
    } else {
      toast.success(t('result.lifetime.extended', { time }))
    }
  }

  /**
   * Forget every cached detection because the page itself is going away
   * (`pagehide`). Uses the keepalive variant, since a normal request would die
   * with the document. Best effort — the entries expire on their own.
   */
  function forgetResultsOnUnload(): void {
    for (const doc of documents.value) {
      if (doc.result !== null) anonymizeApi.forgetResultOnUnload(doc.result.request_id)
    }
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
    // A search bar cannot outlive the panel it belongs to.
    if (doc.searchPanel === id) closeSearch()
    if (doc.focusedPanel === id) doc.focusedPanel = null
  }

  // ---------------------------------------------------------------------
  // Panel search (per document, in the panel the reviewer last worked in)
  // ---------------------------------------------------------------------

  /**
   * Whether the app can search a panel — meaning MARK the hit where the
   * reviewer is looking.
   *
   * A PDF panel renders a browser PDF viewer in an iframe: JavaScript can
   * neither search it nor highlight in it. Searching the text behind it would
   * answer a different question than the one the panel is showing (a hit count
   * about pages that show nothing, or "Kein Treffer" for a name that is
   * plainly visible in the source), so those panels have no search bar at all
   * and the viewer's own find bar is the tool there.
   */
  function isSearchablePanel(panel: ResultPanelId): boolean {
    if (panel === 'pdf') return false
    if (panel === 'original') return !isPdfResult(activeDocument.value?.result ?? null)
    return true
  }

  /** The text a searchable panel is searched against. */
  function panelSearchText(panel: ResultPanelId, response: AnonymizeResponse): string {
    return panel === 'anonymized' ? response.anonymized_text : response.source_text
  }

  const focusedPanel = computed(() => activeDocument.value?.focusedPanel ?? null)
  const searchPanel = computed(() => activeDocument.value?.searchPanel ?? null)

  /** Writable so the search bar can `v-model` it; a new term restarts at hit 1. */
  const searchQuery = computed<string>({
    get: () => activeDocument.value?.searchQuery ?? '',
    set: (value: string) => {
      const doc = activeDocument.value
      if (!doc) return
      doc.searchQuery = value
      doc.searchMatchIndex = 0
    },
  })

  /** Hits of the current term in the searched panel's text, in document order. */
  const searchMatches = computed<MatchRange[]>(() => {
    const doc = activeDocument.value
    if (!doc || doc.result === null || doc.searchPanel === null) return []
    return findMatches(panelSearchText(doc.searchPanel, doc.result), doc.searchQuery)
  })

  /** The active hit, clamped on READ — the hit count changes under it (re-runs). */
  const searchMatchIndex = computed<number>(() => {
    const doc = activeDocument.value
    const total = searchMatches.value.length
    if (!doc || total === 0) return 0
    return Math.min(Math.max(doc.searchMatchIndex, 0), total - 1)
  })

  /** Remember where the reviewer is working; Ctrl/Cmd+F opens the search there. */
  function focusPanel(id: ResultPanelId): void {
    const doc = activeDocument.value
    if (!doc) return
    doc.focusedPanel = id
  }

  function openSearch(id: ResultPanelId): void {
    const doc = activeDocument.value
    if (!doc || !isSearchablePanel(id)) return
    doc.searchPanel = id
    doc.focusedPanel = id
    doc.searchMatchIndex = 0
  }

  function closeSearch(): void {
    const doc = activeDocument.value
    if (!doc) return
    doc.searchPanel = null
  }

  /** Step to the next (+1) or previous (−1) hit, wrapping around. */
  function stepSearch(delta: 1 | -1): void {
    const doc = activeDocument.value
    const total = searchMatches.value.length
    if (!doc || total === 0) return
    doc.searchMatchIndex = (searchMatchIndex.value + delta + total) % total
  }

  /** Search a term in a specific panel — "is this name really gone?" in one click. */
  function searchInPanel(id: ResultPanelId, term: string): void {
    activatePanel(id)
    openSearch(id)
    searchQuery.value = term
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
        doc.forceOcr,
        doc.ocrProfile,
        doc.outputLanguage,
        useSettingsStore().redactionBars,
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

  /**
   * Re-export the preview of every finished SCANNED document — what the
   * redaction-bar option changes. It has to be the whole batch, not just the
   * document on screen: the ZIP export bundles these preview blobs, so leaving
   * the others behind would hand out a batch that disagrees with itself.
   */
  async function refreshReconstructedPreviews(): Promise<void> {
    await Promise.all(
      documents.value
        .filter((doc) => doc.status === 'done' && doc.result?.source_type === 'pdf-ocr')
        .map((doc) => refreshPdfPreviewFor(doc)),
    )
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

  const pdfRedactedPages = computed<PdfPageRender[] | null>(
    () => activeDocument.value?.pdfRedactedPages ?? null,
  )
  const pdfRedactedPagesTruncated = computed(
    () => activeDocument.value?.pdfRedactedPagesTruncated ?? false,
  )
  const pdfRedactedPagesLoading = computed(
    () => activeDocument.value?.pdfRedactedPagesLoading ?? false,
  )
  const pdfRedactedPagesError = computed(() => activeDocument.value?.pdfRedactedPagesError ?? null)
  const areasShowRedacted = computed(() => activeDocument.value?.areasShowRedacted ?? false)

  /** Draw on the redacted pages (or back on the originals). */
  function setAreasShowRedacted(value: boolean): void {
    const doc = activeDocument.value
    if (doc) doc.areasShowRedacted = value
  }

  /**
   * Render the ACTIVE document's REDACTED preview into page images for the
   * area editor's "show automatic redactions" view.
   *
   * The redacted PDF already exists as `pdfPreviewBlob`, so this re-posts
   * those bytes to the page-render route instead of locating entities again:
   * the blackouts are in the pixels, and what the editor shows is by
   * construction what the export contains. A new preview (any override, any
   * drawn area) supersedes the render; the previous pages stay visible until
   * the new ones arrive.
   *
   * `image_boxes` are deliberately NOT taken from this render: a
   * rasterized export is one full-page image per page, so "redact all images"
   * would offer to black out whole pages. Those keep coming from `pdfPages`.
   */
  async function loadRedactedPdfPages(): Promise<void> {
    const doc = activeDocument.value
    if (!doc) return
    const blob = doc.pdfPreviewBlob
    // No redacted preview to render: none generated yet, or the export failed
    // closed. The editor stays on the original pages and says so.
    if (blob === null) return
    // Already rendered (or being rendered) for exactly these bytes.
    if (doc.pdfRedactedPagesSource === blob) return

    doc.pdfRedactedPagesSource = blob
    doc.pdfRedactedPagesError = null
    // The render route is an upload: a rasterized export of a long document
    // can exceed the server's limit, and a 413 is not worth showing here.
    const maxBytes = (status.value?.limits.max_upload_mb ?? 20) * 1024 * 1024
    if (blob.size > maxBytes) {
      doc.pdfRedactedPages = null
      doc.pdfRedactedPagesError = t('areas.redacted_too_large')
      return
    }

    const token = ++doc.pdfRedactedPagesToken
    doc.pdfRedactedPagesLoading = true
    try {
      const file = new File([blob], 'redacted.pdf', { type: 'application/pdf' })
      const { data } = await anonymizeApi.renderPdfPages(file)
      if (token !== doc.pdfRedactedPagesToken) return
      doc.pdfRedactedPages = data.pages
      doc.pdfRedactedPagesTruncated = data.truncated
    } catch (err) {
      if (token !== doc.pdfRedactedPagesToken) return
      doc.pdfRedactedPages = null
      doc.pdfRedactedPagesError = extractApiErrorMessage(err)
    } finally {
      if (token === doc.pdfRedactedPagesToken) doc.pdfRedactedPagesLoading = false
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
            doc.outputLanguage,
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
            doc.policy,
            doc.rules,
            doc.outputLanguage,
          )
        ).data
      }
      doc.result = response
      adoptLifetime(doc, response.lifetime)
      // The selection survives the re-run: it is stored as offsets, so it only
      // has to shed the keys the new result no longer has (a manual span whose
      // override was just dropped). Everything else stays selected, which is
      // what makes "redact these six → no, preserve them after all" work.
      const stillThere = (key: string) => indexOfEntityKey(response.entities, key) !== null
      doc.selectedKeys = doc.selectedKeys.filter(stillThere)
      if (doc.selectionAnchorKey !== null && !stillThere(doc.selectionAnchorKey)) {
        doc.selectionAnchorKey = null
      }
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

  // ---------------------------------------------------------------------
  // Selection (single and multi)
  //
  // Everything below stores override KEYS, never indices — a re-run reorders
  // the entity array but never moves an offset.
  // ---------------------------------------------------------------------

  /** The override key of the entity at `index` in the ACTIVE document. */
  function keyAt(doc: SessionDocument, index: number): string | null {
    const entity = doc.result?.entities[index]
    return entity === undefined ? null : overrideKey(entity)
  }

  /** Plain click: select exactly this entity (`null` clears the selection). */
  function selectEntity(index: number | null): void {
    const doc = activeDocument.value
    if (!doc) return
    if (index === null) {
      doc.selectedKeys = []
      doc.selectionAnchorKey = null
      return
    }
    const key = keyAt(doc, index)
    if (key === null) return
    doc.selectedKeys = [key]
    doc.selectionAnchorKey = key
  }

  /** Ctrl/Cmd-click: add this entity to the selection, or take it back out. */
  function toggleEntitySelection(index: number): void {
    const doc = activeDocument.value
    if (!doc) return
    const key = keyAt(doc, index)
    if (key === null) return
    const without = doc.selectedKeys.filter((entry) => entry !== key)
    // Added entities become the focus; the anchor follows the click either
    // way, so a following shift-click ranges from where the user last was.
    doc.selectedKeys = without.length === doc.selectedKeys.length ? [...without, key] : without
    doc.selectionAnchorKey = key
  }

  /**
   * Shift-click: select everything between the anchor and `index` in document
   * order, inclusive, replacing the selection. Without an anchor (nothing
   * clicked yet) this is a plain click.
   */
  function selectEntityRange(index: number): void {
    const doc = activeDocument.value
    if (!doc || doc.result === null) return
    const entities = doc.result.entities
    const anchorIndex =
      doc.selectionAnchorKey === null ? null : indexOfEntityKey(entities, doc.selectionAnchorKey)
    if (anchorIndex === null) {
      selectEntity(index)
      return
    }
    // Order by offset rather than trusting the array order, so a range always
    // means "everything the reviewer sees between these two marks".
    const byOffset = entities
      .map((entity, position) => ({ position, start: entity.start }))
      .sort((a, b) => a.start - b.start || a.position - b.position)
    const from = byOffset.findIndex((entry) => entry.position === anchorIndex)
    const to = byOffset.findIndex((entry) => entry.position === index)
    if (from === -1 || to === -1) return

    const keys: string[] = []
    for (let step = Math.min(from, to); step <= Math.max(from, to); step++) {
      const key = keyAt(doc, byOffset[step]!.position)
      if (key !== null) keys.push(key)
    }
    // The clicked end is the focus; the anchor stays put so a second
    // shift-click re-ranges from the same origin instead of walking away.
    doc.selectedKeys = from <= to ? keys : keys.reverse()
  }

  /** Entities whose text matches this one after normalization (incl. itself). */
  function matchingEntities(entity: { text: string }): AnonymizedEntity[] {
    const entities = result.value?.entities
    if (!entities) return []
    const target = normalizeEntityText(entity.text)
    return entities.filter((candidate) => normalizeEntityText(candidate.text) === target)
  }

  /** How often this entity's text occurs in the document (incl. itself). */
  function countMatchingEntities(entity: { text: string }): number {
    return matchingEntities(entity).length
  }

  /**
   * "Alle 14 Vorkommen": select every entity carrying the same text. The
   * entity that was already selected stays the focus, so the source view does
   * not jump away from where the reviewer is reading.
   */
  function selectMatchingEntities(entity: AnonymizedEntity): void {
    const doc = activeDocument.value
    if (!doc) return
    const self = overrideKey(entity)
    const keys = matchingEntities(entity).map(overrideKey)
    if (keys.length === 0) return
    doc.selectedKeys = [...keys.filter((key) => key !== self), self]
    doc.selectionAnchorKey = self
  }

  /** Drop the selection without touching any override. */
  function clearSelection(): void {
    selectEntity(null)
  }

  // ---------------------------------------------------------------------
  // Bulk actions on the selection
  //
  // The backend takes overrides as a LIST, so N entities cost exactly ONE
  // re-run — the same round trip a single-entity edit costs today.
  // ---------------------------------------------------------------------

  /**
   * Apply `action` to every selected entity of the ACTIVE document and re-run
   * once. Returns how many entities actually changed, so the caller can report
   * it; entities the action is a no-op for (already redacted, already
   * preserved, no override to reset) are skipped and never counted.
   *
   * Throws like every other override path — the override map is rolled back by
   * `rerunOverridesFor` and the caller shows the error.
   */
  async function applySelectionAction(action: SelectionAction): Promise<number> {
    const doc = activeDocument.value
    if (!doc || doc.result === null) return 0
    const entities = selectedEntities.value
    if (entities.length === 0) return 0

    const previous = new Map(doc.overrides)
    let changed = 0
    for (const entity of entities) {
      const key = overrideKey(entity)
      const isManual = entity.metadata?.user_manual === true
      // Reset, and releasing a manual span, both mean the same thing: forget
      // the override. A manual span has no detection to fall back to.
      if (action === 'reset' || (action === 'preserve' && isManual)) {
        if (doc.overrides.delete(key)) changed += 1
        continue
      }
      // A manual span is already redacted; anything else already redacted keeps
      // the transformation it has (forcing TYPE_MASK here would silently turn
      // a consistent [PERSON_1] tag into a flat [NAME]).
      if (isManual) continue
      if (action === 'redact' && entity.status !== 'PRESERVED') continue
      if (action === 'preserve' && entity.status === 'PRESERVED') continue

      const transformation: TransformationType = action === 'preserve' ? 'PRESERVE' : 'TYPE_MASK'
      const existing = doc.overrides.get(key)
      const next: Override = {
        start: entity.start,
        end: entity.end,
        text: entity.text,
        transformation,
      }
      if (existing?.entity_type !== undefined) next.entity_type = existing.entity_type
      doc.overrides.set(key, next)
      changed += 1
    }

    if (changed === 0) return 0
    await rerunOverridesFor(doc, previous)
    return changed
  }

  /**
   * Set one entity type on every selected entity and re-run once. Like the
   * single-entity path, this drops any transformation override so the new
   * type's policy applies; manual spans have no type and are skipped.
   */
  async function applySelectionType(entityType: EntityType): Promise<number> {
    const doc = activeDocument.value
    if (!doc || doc.result === null) return 0
    const previous = new Map(doc.overrides)
    let changed = 0
    for (const entity of selectedEntities.value) {
      if (entity.metadata?.user_manual === true) continue
      if (entity.entity_type === entityType) continue
      doc.overrides.set(overrideKey(entity), {
        start: entity.start,
        end: entity.end,
        text: entity.text,
        entity_type: entityType,
      })
      changed += 1
    }
    if (changed === 0) return 0
    await rerunOverridesFor(doc, previous)
    return changed
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
    selectedEntityIndices,
    selectedEntity,
    selectedEntities,
    entityCounts,
    overrides,
    rerunning,
    policy,
    policyOverrides,
    policyCustomized,
    customInstruction,
    redactTerms,
    preserveTerms,
    forceOcr,
    ocrProfile,
    outputLanguage,
    outputLanguageOverride,
    setOutputLanguage,
    customRules,
    advancedCustomized,
    setPolicyTransformation,
    resetAdvancedSettings,
    activePanels,
    activatePanel,
    togglePanel,
    focusedPanel,
    focusPanel,
    isSearchablePanel,
    searchPanel,
    searchQuery,
    searchMatches,
    searchMatchIndex,
    openSearch,
    closeSearch,
    stepSearch,
    searchInPanel,
    pdfPreviewUrl,
    pdfPreviewBlob,
    pdfPreviewLoading,
    pdfPreviewError,
    refreshPdfPreview,
    refreshReconstructedPreviews,
    originalPreviewUrl,
    ensureOriginalPreviewUrl,
    redactAreas,
    pdfPages,
    pdfPagesTruncated,
    pdfPagesLoading,
    pdfPagesError,
    loadPdfPages,
    pdfRedactedPages,
    pdfRedactedPagesTruncated,
    pdfRedactedPagesLoading,
    pdfRedactedPagesError,
    loadRedactedPdfPages,
    areasShowRedacted,
    setAreasShowRedacted,
    addRedactArea,
    removeRedactArea,
    addImageAreas,
    status,
    banner,
    externalEndpoints,
    notReadyDetectors,
    fetchStatus,
    submitText,
    submitFiles,
    selectEntity,
    toggleEntitySelection,
    selectEntityRange,
    selectMatchingEntities,
    countMatchingEntities,
    clearSelection,
    applySelectionAction,
    applySelectionType,
    overrideFor,
    applyEntityOverride,
    addManualRedaction,
    resetEntityOverride,
    rerunOverrides,
    reset,
    resultsExpireAt,
    resultsCanExtend,
    extendingResults,
    extendResults,
    forgetResultsOnUnload,
  }
})
