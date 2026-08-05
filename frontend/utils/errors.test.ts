import { describe, expect, it } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import {
  extractApiErrorMessage,
  extractPdfExportErrorMessage,
  isExpiredResultError,
} from '@/utils/errors'

function apiError(status: number, data?: unknown): AxiosError {
  const error = new AxiosError('request failed')
  error.response = {
    status,
    statusText: '',
    data,
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
  }
  return error
}

function networkError(): AxiosError {
  return new AxiosError('Network Error')
}

describe('isExpiredResultError', () => {
  it('recognizes the expired-cache status', () => {
    expect(isExpiredResultError(apiError(410))).toBe(true)
  })

  it('is false for other errors', () => {
    expect(isExpiredResultError(apiError(500))).toBe(false)
    expect(isExpiredResultError(new Error('boom'))).toBe(false)
  })
})

describe('extractApiErrorMessage', () => {
  it('explains a scanned PDF without OCR', () => {
    const message = extractApiErrorMessage(
      apiError(422, { detail: 'The PDF appears to be scanned; no OCR engine is configured.' }),
    )

    expect(message).toContain('gescannt')
  })

  it('states plainly that an unreachable LLM left the document unanonymized', () => {
    const message = extractApiErrorMessage(
      apiError(503, {
        detail: "Detector 'llm' is enabled but ... the document was NOT anonymized.",
      }),
    )

    expect(message).toContain('NICHT anonymisiert')
  })

  it('passes through other 502/503 details unchanged', () => {
    expect(extractApiErrorMessage(apiError(502, { detail: 'OCR-Dienst antwortet nicht.' }))).toBe(
      'OCR-Dienst antwortet nicht.',
    )
  })

  it('maps known status codes without a detail', () => {
    expect(extractApiErrorMessage(apiError(413))).toBe('Datei zu groß.')
    expect(extractApiErrorMessage(apiError(415))).toBe('Dateityp nicht unterstützt.')
  })

  it('prefers the backend detail for unmapped statuses', () => {
    expect(extractApiErrorMessage(apiError(400, { detail: 'Ungültige Anfrage.' }))).toBe(
      'Ungültige Anfrage.',
    )
  })

  it('reports an unreachable backend when there is no response', () => {
    expect(extractApiErrorMessage(networkError())).toContain('Server nicht erreichbar')
  })

  it('falls back for non-axios errors', () => {
    expect(extractApiErrorMessage(new Error('boom'), 'Fallback')).toBe('Fallback')
  })
})

describe('extractPdfExportErrorMessage', () => {
  it('parses a JSON detail delivered as a Blob (responseType: blob)', async () => {
    const blob = new Blob([JSON.stringify({ detail: 'redaction could not be verified' })], {
      type: 'application/json',
    })

    await expect(extractPdfExportErrorMessage(apiError(422, blob))).resolves.toBe(
      'PDF-Export fehlgeschlagen: redaction could not be verified',
    )
  })

  it('falls back to the generic message for an unparsable body', async () => {
    const blob = new Blob(['<html>oops</html>'], { type: 'text/html' })

    await expect(extractPdfExportErrorMessage(apiError(500, blob))).resolves.toContain(
      'PDF-Export fehlgeschlagen',
    )
  })
})
