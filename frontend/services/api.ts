import axios, { isAxiosError } from 'axios'

// In dev mode (Vite dev server), use absolute URL to backend.
// In production (nginx serves SPA), use relative path — nginx proxies /api/ to backend.
const getBaseURL = () => {
  if (import.meta.env.DEV) {
    return 'http://localhost:8000/api/v1'
  }
  return '/api/v1'
}

/**
 * Shared axios instance (llmaixweb pattern). Components never import this
 * directly: call the typed `services/*Api.ts` modules instead.
 *
 * `withCredentials` carries the session cookie of the optional OIDC gate. It
 * matters only in dev, where Vite (:5173) and the backend (:8000) are
 * different origins; in production nginx serves both from one origin. Safe
 * because the backend's CORS origins are an explicit list, never `*`.
 */
export const api = axios.create({
  baseURL: getBaseURL(),
  withCredentials: true,
})

let unauthorizedHandler: (() => void) | null = null

/**
 * Register what happens when the backend says "not signed in". The auth store
 * registers itself here rather than this module importing the store — that
 * would be a cycle, since the store calls the API.
 */
export function setUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler
}

/** A 401 arrived: the gate is on and this session is over. */
export function notifyUnauthorized(): void {
  unauthorizedHandler?.()
}

api.interceptors.response.use(undefined, (error: unknown) => {
  if (isAxiosError(error) && error.response?.status === 401) {
    notifyUnauthorized()
  }
  return Promise.reject(error)
})
