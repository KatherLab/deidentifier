import type { AxiosResponse } from 'axios'
import { api } from '@/services/api'
import type {
  AnonymizeRerunRequest,
  AnonymizeResponse,
  AnonymizeTextRequest,
  Override,
  PolicyMap,
} from '@/types/anonymizer'

/** True when a policy carries at least one deviation worth sending. */
function hasPolicyEntries(policy?: PolicyMap | null): policy is PolicyMap {
  return policy != null && Object.keys(policy).length > 0
}

export const anonymizeApi = {
  /**
   * Anonymize pasted text (JSON body). Pass `overrides` to re-run from the
   * full text with user overrides applied (used when the cached detection of
   * a previous request has expired — 410). `policy` carries the deviations
   * from the default policy (advanced settings), if any.
   */
  anonymizeText(
    text: string,
    overrides?: Override[],
    policy?: PolicyMap | null,
  ): Promise<AxiosResponse<AnonymizeResponse>> {
    const body: AnonymizeTextRequest = { text }
    if (overrides && overrides.length > 0) body.overrides = overrides
    if (hasPolicyEntries(policy)) body.policy = policy
    return api.post<AnonymizeResponse>('/anonymize', body)
  },

  /**
   * Cheap re-run from the backend's cached detection (no re-detection).
   * Returns the SAME request_id; rejects with 410 if the cache has expired.
   */
  rerunWithOverrides(
    requestId: string,
    overrides: Override[],
    policy?: PolicyMap | null,
  ): Promise<AxiosResponse<AnonymizeResponse>> {
    const body: AnonymizeRerunRequest = { request_id: requestId, overrides }
    if (hasPolicyEntries(policy)) body.policy = policy
    return api.post<AnonymizeResponse>('/anonymize', body)
  },

  /** Anonymize an uploaded file (multipart/form-data, field `file`). */
  anonymizeFile(file: File, policy?: PolicyMap | null): Promise<AxiosResponse<AnonymizeResponse>> {
    const formData = new FormData()
    formData.append('file', file)
    if (hasPolicyEntries(policy)) formData.append('policy', JSON.stringify(policy))
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
  ): Promise<AxiosResponse<Blob>> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('request_id', requestId)
    if (overrides.length > 0) formData.append('overrides', JSON.stringify(overrides))
    if (hasPolicyEntries(policy)) formData.append('policy', JSON.stringify(policy))
    return api.post<Blob>('/export/pdf', formData, { responseType: 'blob' })
  },
}
