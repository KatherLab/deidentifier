/**
 * Maps API errors to user-facing messages (llmaixweb's extractErrorMessage
 * pattern, adapted for the anonymizer's error contract: `{"detail": string}`
 * bodies with known status codes).
 *
 * Backend `detail` strings are English; the cases users actually hit are
 * translated here via the `errors.*` catalog keys. Anything unmapped falls
 * through to the backend text rather than to a generic message.
 */
import { isAxiosError } from 'axios'
import { t } from '@/i18n'

const STATUS_MESSAGE_KEYS: Record<number, string> = {
  410: 'errors.expired',
  413: 'errors.too_large',
  415: 'errors.unsupported_type',
  501: 'errors.ocr_unavailable',
}

/**
 * True when the backend reports the cached detection result as expired (410).
 * The session store handles this automatically by re-posting the full source
 * text; only toast the 410 message if that automatic retry also fails.
 */
export function isExpiredResultError(err: unknown): boolean {
  return isAxiosError(err) && err.response?.status === 410
}

/**
 * Error message for the redacted-PDF export. The export request uses
 * `responseType: 'blob'`, so error bodies arrive as a Blob and must be parsed
 * back into `{"detail": string}` before the usual mapping. A 422 detail (e.g.
 * "redaction could not be verified") is user-appropriate English from the
 * backend — surface it behind a translated prefix.
 */
export async function extractPdfExportErrorMessage(err: unknown): Promise<string> {
  if (isAxiosError(err) && err.response && err.response.data instanceof Blob) {
    try {
      err.response.data = JSON.parse(await err.response.data.text())
    } catch {
      // Not a JSON body — fall through to the status-based mapping.
      err.response.data = undefined
    }
  }
  if (isAxiosError(err) && err.response?.status === 422) {
    const data = err.response.data as { detail?: unknown } | undefined
    const detail = typeof data?.detail === 'string' ? data.detail.trim() : ''
    if (detail) return t('errors.pdf_export_detail', { detail })
  }
  return extractApiErrorMessage(err, t('errors.pdf_export_failed'))
}

export function extractApiErrorMessage(err: unknown, fallback?: string): string {
  if (isAxiosError(err)) {
    const status = err.response?.status
    const data = err.response?.data as { detail?: unknown } | undefined
    const detail = typeof data?.detail === 'string' ? data.detail.trim() : ''

    // 422 for a scanned PDF without OCR configured.
    if (status === 422 && detail.toLowerCase().includes('scanned')) {
      return t('errors.scanned_no_ocr')
    }
    // 502/503: the backend detail is user-appropriate, but translate the
    // common case of an unreachable LLM endpoint.
    if (status === 502 || status === 503) {
      if (detail.toLowerCase().includes('llm')) {
        return t('errors.llm_unreachable')
      }
      if (detail) return detail
    }
    const statusKey = status === undefined ? undefined : STATUS_MESSAGE_KEYS[status]
    if (statusKey) {
      return t(statusKey)
    }
    if (detail) {
      return detail
    }
    if (!err.response) {
      return t('errors.backend_unreachable')
    }
  }
  return fallback ?? t('errors.generic')
}
