import type { AxiosResponse } from 'axios'
import { api } from '@/services/api'
import type {
  AnonymizeRerunRequest,
  AnonymizeResponse,
  AnonymizeTextRequest,
  Override,
} from '@/types/anonymizer'

export const anonymizeApi = {
  /**
   * Anonymize pasted text (JSON body). Pass `overrides` to re-run from the
   * full text with user overrides applied (used when the cached detection of
   * a previous request has expired — 410).
   */
  anonymizeText(text: string, overrides?: Override[]): Promise<AxiosResponse<AnonymizeResponse>> {
    const body: AnonymizeTextRequest = { text }
    if (overrides && overrides.length > 0) body.overrides = overrides
    return api.post<AnonymizeResponse>('/anonymize', body)
  },

  /**
   * Cheap re-run from the backend's cached detection (no re-detection).
   * Returns the SAME request_id; rejects with 410 if the cache has expired.
   */
  rerunWithOverrides(
    requestId: string,
    overrides: Override[],
  ): Promise<AxiosResponse<AnonymizeResponse>> {
    const body: AnonymizeRerunRequest = { request_id: requestId, overrides }
    return api.post<AnonymizeResponse>('/anonymize', body)
  },

  /** Anonymize an uploaded file (multipart/form-data, field `file`). */
  anonymizeFile(file: File): Promise<AxiosResponse<AnonymizeResponse>> {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<AnonymizeResponse>('/anonymize', formData)
  },

  /**
   * Export a redacted PDF (multipart/form-data). The ORIGINAL PDF is re-sent
   * because the server stores nothing; `requestId` lets it reuse the cached
   * detection (no second OCR/LLM run). Resolves with the PDF bytes as a Blob.
   * Can take up to a minute for scans on a cache miss.
   */
  exportPdf(file: File, requestId: string, overrides: Override[]): Promise<AxiosResponse<Blob>> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('request_id', requestId)
    if (overrides.length > 0) formData.append('overrides', JSON.stringify(overrides))
    return api.post<Blob>('/export/pdf', formData, { responseType: 'blob' })
  },
}
