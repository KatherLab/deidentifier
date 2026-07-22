import axios from 'axios'

// In dev mode (Vite dev server), use absolute URL to backend.
// In production (nginx serves SPA), use relative path — nginx proxies /api/ to backend.
const getBaseURL = () => {
  if (import.meta.env.DEV) {
    return 'http://localhost:8000/api/v1'
  }
  return '/api/v1'
}

/**
 * Shared axios instance (llmaixweb pattern, minus auth — the anonymizer has
 * no login; a hospital proxy fronts the app). Components never import this
 * directly: call the typed `services/*Api.ts` modules instead.
 */
export const api = axios.create({
  baseURL: getBaseURL(),
})
