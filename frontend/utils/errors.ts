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
import { hasMessage, t } from '@/i18n'

const STATUS_MESSAGE_KEYS: Record<number, string> = {
  // Only reachable with the sign-in gate on: the session ran out mid-work.
  401: 'errors.unauthorized',
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
 * A refused redacted-PDF export, in the form the review UI acts on.
 *
 * `forceable` is the backend's judgement, never re-derived here: only it knows
 * whether the finding is one the anonymized text download carries too (a
 * passage the reviewer kept that also occurs in redacted form) or a blackout
 * that failed to apply. `items` are the passages that would stay visible —
 * document content, so they live in memory and never in a log or storage.
 * `count` is how many there are: `items` is capped for display, and a notice
 * that undercounts is worse than one that lists fewer examples.
 */
export interface PdfExportFailure {
  message: string
  code: string | null
  forceable: boolean
  items: string[]
  count: number
}

/**
 * Parse an export error. The request uses `responseType: 'blob'`, so error
 * bodies arrive as a Blob and must be read back into JSON before the usual
 * mapping. A known `code` is translated; anything else falls back to the
 * backend's English `detail` behind a translated prefix.
 */
export async function parsePdfExportError(err: unknown): Promise<PdfExportFailure> {
  if (isAxiosError(err) && err.response && err.response.data instanceof Blob) {
    try {
      err.response.data = JSON.parse(await err.response.data.text())
    } catch {
      // Not a JSON body — fall through to the status-based mapping.
      err.response.data = undefined
    }
  }
  const data = isAxiosError(err)
    ? (err.response?.data as
        | {
            detail?: unknown
            code?: unknown
            items?: unknown
            forceable?: unknown
            count?: unknown
          }
        | undefined)
    : undefined
  const code = typeof data?.code === 'string' ? data.code : null
  const items = Array.isArray(data?.items) ? data.items.filter((i) => typeof i === 'string') : []
  const forceable = data?.forceable === true
  const count = typeof data?.count === 'number' ? data.count : items.length

  const key = code === null ? null : `errors.export.${code}`
  if (key !== null && hasMessage(key)) {
    return { message: t(key, { count }), code, forceable, items, count }
  }
  const detail = typeof data?.detail === 'string' ? data.detail.trim() : ''
  if (isAxiosError(err) && err.response?.status === 422 && detail) {
    return { message: t('errors.pdf_export_detail', { detail }), code, forceable, items, count }
  }
  return {
    message: extractApiErrorMessage(err, t('errors.pdf_export_failed')),
    code,
    forceable,
    items,
    count,
  }
}

/** The message alone, for the places that only show one (toasts). */
export async function extractPdfExportErrorMessage(err: unknown): Promise<string> {
  return (await parsePdfExportError(err)).message
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
