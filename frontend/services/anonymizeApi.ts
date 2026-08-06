import type { AxiosResponse } from 'axios'
import { api } from '@/services/api'
import type {
  AnonymizeRerunRequest,
  AnonymizeResponse,
  AnonymizeTextRequest,
  CacheLifetime,
  CustomRules,
  OutputLanguage,
  Override,
  PdfPagesResponse,
  PolicyMap,
  RedactArea,
} from '@/types/anonymizer'

/** True when a policy carries at least one deviation worth sending. */
export function hasPolicyEntries(policy?: PolicyMap | null): policy is PolicyMap {
  return policy != null && Object.keys(policy).length > 0
}

/**
 * Append the custom-rule form fields to a multipart request. Backend contract:
 * `custom_instruction` is a plain string, the term lists are JSON-stringified
 * arrays — each field only present when non-empty. Also used by the streaming
 * variants in `services/anonymizeStream.ts`.
 */
export function appendCustomRules(formData: FormData, rules?: CustomRules | null): void {
  if (!rules) return
  if (rules.customInstruction.length > 0) {
    formData.append('custom_instruction', rules.customInstruction)
  }
  if (rules.redactTerms.length > 0) {
    formData.append('redact_terms', JSON.stringify(rules.redactTerms))
  }
  if (rules.preserveTerms.length > 0) {
    formData.append('preserve_terms', JSON.stringify(rules.preserveTerms))
  }
}

export const anonymizeApi = {
  /**
   * Anonymize pasted text (JSON body). Pass `overrides` to re-run from the
   * full text with user overrides applied (used when the cached detection of
   * a previous request has expired — 410). `policy` carries the deviations
   * from the default policy (advanced settings), if any; `rules` the custom
   * rules (extra redact/preserve terms + LLM instruction), if any.
   */
  anonymizeText(
    text: string,
    overrides?: Override[],
    policy?: PolicyMap | null,
    rules?: CustomRules | null,
    outputLanguage?: OutputLanguage | null,
  ): Promise<AxiosResponse<AnonymizeResponse>> {
    const body: AnonymizeTextRequest = { text }
    if (overrides && overrides.length > 0) body.overrides = overrides
    if (hasPolicyEntries(policy)) body.policy = policy
    if (outputLanguage) body.output_language = outputLanguage
    if (rules) {
      if (rules.customInstruction.length > 0) body.custom_instruction = rules.customInstruction
      if (rules.redactTerms.length > 0) body.redact_terms = rules.redactTerms
      if (rules.preserveTerms.length > 0) body.preserve_terms = rules.preserveTerms
    }
    return api.post<AnonymizeResponse>('/anonymize', body)
  },

  /**
   * Cheap re-run from the backend's cached detection (no re-detection).
   * Returns the SAME request_id; rejects with 410 if the cache has expired.
   * Only `preserveTerms` can be sent here — redact terms and the custom
   * instruction affect detection and are baked into the cached result.
   */
  rerunWithOverrides(
    requestId: string,
    overrides: Override[],
    policy?: PolicyMap | null,
    preserveTerms?: string[] | null,
    outputLanguage?: OutputLanguage | null,
  ): Promise<AxiosResponse<AnonymizeResponse>> {
    const body: AnonymizeRerunRequest = { request_id: requestId, overrides }
    if (hasPolicyEntries(policy)) body.policy = policy
    if (preserveTerms && preserveTerms.length > 0) body.preserve_terms = preserveTerms
    // Re-sent so an adjusted document keeps the placeholders it already shows
    // (the backend also remembers the run's language for cached re-runs).
    if (outputLanguage) body.output_language = outputLanguage
    return api.post<AnonymizeResponse>('/anonymize', body)
  },

  /**
   * Keep a cached result available for another window. Rejects with 410 once
   * the entry is gone (the caller then falls back to re-sending the text), and
   * resolves with `can_extend: false` once the hard ceiling is reached.
   */
  extendResult(requestId: string): Promise<AxiosResponse<CacheLifetime>> {
    return api.post<CacheLifetime>(`/anonymize/${encodeURIComponent(requestId)}/extend`)
  },

  /**
   * Ask the backend to forget one cached detection now, instead of letting it
   * expire. Fire-and-forget: the entry is short-lived either way, so a failure
   * here is never worth interrupting the user for.
   */
  forgetResult(requestId: string): Promise<void> {
    return api
      .delete(`/anonymize/${encodeURIComponent(requestId)}`)
      .then(() => undefined)
      .catch(() => undefined)
  },

  /**
   * Same, but from a page that is going away (`pagehide`). axios is XHR-based
   * and its request would be cancelled with the document, so this uses fetch's
   * `keepalive` — the browser finishes it after the page is gone.
   */
  forgetResultOnUnload(requestId: string): void {
    try {
      void fetch(`${api.defaults.baseURL}/anonymize/${encodeURIComponent(requestId)}`, {
        method: 'DELETE',
        keepalive: true,
      }).catch(() => undefined)
    } catch {
      /* the page is unloading — nothing left to report to */
    }
  },

  /** Anonymize an uploaded file (multipart/form-data, field `file`). */
  anonymizeFile(
    file: File,
    policy?: PolicyMap | null,
    rules?: CustomRules | null,
    forceOcr?: boolean,
    outputLanguage?: OutputLanguage | null,
  ): Promise<AxiosResponse<AnonymizeResponse>> {
    const formData = new FormData()
    formData.append('file', file)
    if (hasPolicyEntries(policy)) formData.append('policy', JSON.stringify(policy))
    appendCustomRules(formData, rules)
    if (outputLanguage) formData.append('output_language', outputLanguage)
    if (forceOcr) formData.append('force_ocr', 'true')
    return api.post<AnonymizeResponse>('/anonymize', formData)
  },

  /**
   * Export a redacted PDF (multipart/form-data). The ORIGINAL PDF is re-sent
   * because the server stores nothing; `requestId` lets it reuse the cached
   * detection (no second OCR/LLM run). Resolves with the PDF bytes as a Blob.
   * Can take up to a minute for scans on a cache miss.
   */
  exportPdf(
    file: File,
    requestId: string,
    overrides: Override[],
    policy?: PolicyMap | null,
    rules?: CustomRules | null,
    areas?: RedactArea[] | null,
    forceOcr?: boolean,
    outputLanguage?: OutputLanguage | null,
  ): Promise<AxiosResponse<Blob>> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('request_id', requestId)
    if (overrides.length > 0) formData.append('overrides', JSON.stringify(overrides))
    if (hasPolicyEntries(policy)) formData.append('policy', JSON.stringify(policy))
    appendCustomRules(formData, rules)
    if (areas && areas.length > 0) formData.append('redact_areas', JSON.stringify(areas))
    if (outputLanguage) formData.append('output_language', outputLanguage)
    // Re-sent so a cache-miss re-extraction matches the original forced-OCR run.
    if (forceOcr) formData.append('force_ocr', 'true')
    return api.post<Blob>('/export/pdf', formData, { responseType: 'blob' })
  },

  /**
   * Render the pages of a PDF as PNGs for the area-redaction editor (the
   * original file is re-sent; the server stores nothing). Includes
   * embedded-image bounding boxes as one-click redaction suggestions.
   */
  renderPdfPages(file: File): Promise<AxiosResponse<PdfPagesResponse>> {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<PdfPagesResponse>('/export/pdf/pages', formData)
  },
}
