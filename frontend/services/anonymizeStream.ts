/**
 * Streaming variants of the anonymize endpoint, used for FRESH runs so the UI
 * can show real progress (override re-runs stay on the fast JSON endpoint in
 * `services/anonymizeApi.ts`).
 *
 * POST /anonymize/stream responds with NDJSON (application/x-ndjson), one JSON
 * object per line:
 *   {"event":"progress","stage":"ocr"|"detection"|"recheck","done":n,"total":m}
 *   {"event":"result","data":<AnonymizeResponse>}          (final line, success)
 *   {"event":"error","status":<httpStatus>,"detail":"..."} (final line, failure)
 * Malformed requests fail BEFORE streaming with a normal HTTP error body
 * ({"detail": ...}).
 *
 * axios cannot stream response bodies in browsers, so this module uses
 * fetch() + ReadableStream directly. Errors are re-thrown in an
 * axios-compatible shape (`isAxiosError: true` + `response.{status,data}`) so
 * the existing mapping in `utils/errors.ts` (extractApiErrorMessage) keeps
 * working unchanged.
 */
import { api } from '@/services/api'
import { appendCustomRules, hasPolicyEntries } from '@/services/anonymizeApi'
import type {
  AnonymizeResponse,
  AnonymizeTextRequest,
  CustomRules,
  PolicyMap,
  StreamProgressEvent,
} from '@/types/anonymizer'

export type OnStreamProgress = (event: StreamProgressEvent) => void

/** The NDJSON line shapes emitted by the backend. */
type StreamEvent =
  | ({ event: 'progress' } & StreamProgressEvent)
  | { event: 'result'; data: AnonymizeResponse }
  | { event: 'error'; status: number; detail: string }

interface AxiosLikeError extends Error {
  isAxiosError: boolean
  response?: { status: number; data: unknown }
}

/**
 * Build an axios-shaped error so `isAxiosError()` and the status/detail
 * mapping in `utils/errors.ts` treat it like any other API error. Without a
 * status the error mimics an axios network error (no `response`).
 */
function axiosLikeError(status?: number, data?: unknown): AxiosLikeError {
  const detail = (data as { detail?: unknown } | undefined)?.detail
  const message =
    typeof detail === 'string' && detail.length > 0
      ? detail
      : status !== undefined
        ? `Request failed with status code ${status}`
        : 'Network Error'
  const error = new Error(message) as AxiosLikeError
  error.isAxiosError = true
  if (status !== undefined) error.response = { status, data }
  return error
}

/**
 * POST to /anonymize/stream and consume the NDJSON body. Progress events go to
 * `onProgress`; resolves with the final result, rejects with an axios-shaped
 * error on HTTP or pipeline failure.
 */
async function streamAnonymize(
  body: BodyInit,
  headers: HeadersInit | undefined,
  onProgress: OnStreamProgress,
  signal?: AbortSignal,
): Promise<AnonymizeResponse> {
  let response: Response
  try {
    response = await fetch(`${api.defaults.baseURL}/anonymize/stream`, {
      method: 'POST',
      headers,
      body,
      signal,
    })
  } catch (err) {
    // Deliberate aborts (reset while streaming) keep their AbortError shape so
    // callers can tell them apart from real failures.
    if (signal?.aborted) throw err
    // fetch itself failed (backend down, CORS, …) — mimic an axios network
    // error so the "Server nicht erreichbar" message applies.
    throw axiosLikeError()
  }

  if (!response.ok) {
    // Request rejected before streaming — a normal HTTP error with a JSON
    // {"detail": ...} body (or none).
    let data: unknown
    try {
      data = await response.json()
    } catch {
      data = undefined
    }
    throw axiosLikeError(response.status, data)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('Streaming response has no body')

  /**
   * Handle one NDJSON line. Returns the final result when this line carries
   * it, throws on an error event, ignores blank/malformed lines.
   */
  function handleLine(line: string): AnonymizeResponse | undefined {
    const trimmed = line.trim()
    if (trimmed.length === 0) return undefined
    let event: StreamEvent
    try {
      event = JSON.parse(trimmed) as StreamEvent
    } catch {
      return undefined // tolerate malformed lines instead of aborting the run
    }
    if (event.event === 'progress') {
      onProgress({ stage: event.stage, done: event.done, total: event.total })
      return undefined
    }
    if (event.event === 'result') return event.data
    if (event.event === 'error') throw axiosLikeError(event.status, { detail: event.detail })
    return undefined
  }

  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // Complete lines end in "\n"; the last split element is a partial line
      // (or "") and stays buffered until more bytes arrive.
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        const result = handleLine(line)
        if (result !== undefined) return result
      }
    }
    // The final line may arrive without a trailing newline.
    buffer += decoder.decode()
    const result = handleLine(buffer)
    if (result !== undefined) return result
  } finally {
    // Release the connection whether we returned early or the stream ended.
    void reader.cancel().catch(() => {})
  }
  // Stream ended without a result/error line (connection dropped mid-run).
  throw new Error('Stream ended without a result')
}

/** Streaming counterpart of `anonymizeApi.anonymizeText` (fresh runs only). */
export function anonymizeTextStream(
  text: string,
  policy: PolicyMap | null,
  rules: CustomRules | null,
  onProgress: OnStreamProgress,
  signal?: AbortSignal,
): Promise<AnonymizeResponse> {
  const body: AnonymizeTextRequest = { text }
  if (hasPolicyEntries(policy)) body.policy = policy
  if (rules) {
    if (rules.customInstruction.length > 0) body.custom_instruction = rules.customInstruction
    if (rules.redactTerms.length > 0) body.redact_terms = rules.redactTerms
    if (rules.preserveTerms.length > 0) body.preserve_terms = rules.preserveTerms
  }
  return streamAnonymize(
    JSON.stringify(body),
    { 'Content-Type': 'application/json' },
    onProgress,
    signal,
  )
}

/** Streaming counterpart of `anonymizeApi.anonymizeFile` (fresh runs only). */
export function anonymizeFileStream(
  file: File,
  policy: PolicyMap | null,
  rules: CustomRules | null,
  forceOcr: boolean,
  onProgress: OnStreamProgress,
  signal?: AbortSignal,
): Promise<AnonymizeResponse> {
  const formData = new FormData()
  formData.append('file', file)
  if (hasPolicyEntries(policy)) formData.append('policy', JSON.stringify(policy))
  appendCustomRules(formData, rules)
  if (forceOcr) formData.append('force_ocr', 'true')
  // No explicit headers — the browser sets the multipart boundary itself.
  return streamAnonymize(formData, undefined, onProgress, signal)
}
