/**
 * Maps API errors to German-friendly user messages (llmaixweb's
 * extractErrorMessage pattern, adapted for the anonymizer's error contract:
 * `{"detail": string}` bodies with known status codes).
 */
import { isAxiosError } from 'axios'

const STATUS_MESSAGES: Record<number, string> = {
  410: 'Ergebnis abgelaufen – wird neu berechnet',
  413: 'Datei zu groß.',
  415: 'Dateityp nicht unterstützt.',
  501: 'Diese OCR-Engine ist noch nicht verfügbar',
}

/**
 * True when the backend reports the cached detection result as expired (410).
 * The session store handles this automatically by re-posting the full source
 * text; only toast the 410 message if that automatic retry also fails.
 */
export function isExpiredResultError(err: unknown): boolean {
  return isAxiosError(err) && err.response?.status === 410
}

export function extractApiErrorMessage(
  err: unknown,
  fallback = 'Anonymisierung fehlgeschlagen. Bitte versuchen Sie es erneut.',
): string {
  if (isAxiosError(err)) {
    const status = err.response?.status
    const data = err.response?.data as { detail?: unknown } | undefined
    const detail = typeof data?.detail === 'string' ? data.detail.trim() : ''

    // 422 for a scanned PDF without OCR configured.
    if (status === 422 && detail.toLowerCase().includes('scanned')) {
      return 'Dieses PDF scheint gescannt zu sein. OCR ist nicht aktiviert.'
    }
    // 502/503: the backend detail is user-appropriate, but translate the
    // common case of an unreachable LLM endpoint.
    if (status === 502 || status === 503) {
      if (detail.toLowerCase().includes('llm')) {
        return 'Der KI-Erkennungsdienst ist nicht erreichbar. Das Dokument wurde NICHT anonymisiert.'
      }
      if (detail) return detail
    }
    if (status !== undefined && STATUS_MESSAGES[status]) {
      return STATUS_MESSAGES[status]
    }
    if (detail) {
      return detail
    }
    if (!err.response) {
      return 'Server nicht erreichbar. Bitte prüfen Sie, ob das Backend läuft.'
    }
  }
  return fallback
}
