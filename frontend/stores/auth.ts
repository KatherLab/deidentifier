/**
 * The optional sign-in gate.
 *
 * With no gate configured (`OIDC_ENABLED=false`, the default) this store
 * settles on `enabled=false, authenticated=true` and the app behaves exactly
 * as it did before OIDC existed — `blocked` is never true and nothing else in
 * the UI changes.
 *
 * Nothing here is persisted. The session lives in an HttpOnly cookie the
 * browser handles on its own, which is also why signing in is a full-page
 * navigation rather than an XHR.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/services/authApi'
import { setUnauthorizedHandler } from '@/services/api'
import type { AuthErrorCode, AuthUser } from '@/types/auth'

const AUTH_ERROR_CODES: AuthErrorCode[] = ['denied', 'state', 'provider', 'token', 'identity']

/**
 * Read (and clear) the `?auth_error=` the backend redirects back with after a
 * failed sign-in. Clearing it matters: without that, a reload would show the
 * same stale failure over a session that is by then perfectly fine.
 */
function takeAuthErrorFromUrl(): AuthErrorCode | 'unknown' | null {
  const value = new URLSearchParams(window.location.search).get('auth_error')
  if (value === null) return null
  const url = new URL(window.location.href)
  url.searchParams.delete('auth_error')
  window.history.replaceState({}, '', url.toString())
  return (AUTH_ERROR_CODES as string[]).includes(value) ? (value as AuthErrorCode) : 'unknown'
}

export const useAuthStore = defineStore('auth', () => {
  /** Whether this deployment has a gate at all. */
  const enabled = ref(false)
  const authenticated = ref(false)
  const user = ref<AuthUser | null>(null)
  const loginUrl = ref('')
  /** False until the first `/auth/session` answered — the app waits for it
   *  rather than flashing the input panel at someone who may not be let in. */
  const ready = ref(false)
  const signingOut = ref(false)
  /** The reason the last sign-in attempt failed, or 'expired' for a session
   *  that ran out while the tab was open. */
  const problem = ref<AuthErrorCode | 'unknown' | 'expired' | null>(null)

  /** True exactly when the sign-in screen must replace the app. */
  const blocked = computed(() => enabled.value && !authenticated.value)

  async function fetchSession(): Promise<void> {
    try {
      const { data } = await authApi.getSession()
      enabled.value = data.enabled
      authenticated.value = data.authenticated
      user.value = data.user
      loginUrl.value = data.login_url
    } catch {
      // The backend is unreachable, which is not the same as being locked out:
      // stay out of the way and let the usual "server not reachable" errors
      // surface where they always did.
      enabled.value = false
      authenticated.value = true
      user.value = null
    } finally {
      ready.value = true
    }
  }

  /** A 401 came back mid-session: the cookie expired or was revoked. */
  function markSignedOut(): void {
    if (!enabled.value || !authenticated.value) return
    authenticated.value = false
    user.value = null
    problem.value = 'expired'
  }

  function signIn(): void {
    problem.value = null
    // A full-page navigation, not an XHR: the provider needs to own the tab in
    // order to show its own login screen (and any second factor).
    window.location.href = loginUrl.value || '/api/v1/auth/login'
  }

  async function signOut(): Promise<void> {
    if (signingOut.value) return
    signingOut.value = true
    let redirectUrl: string | null = null
    try {
      redirectUrl = (await authApi.logout()).data.redirect_url
    } catch {
      // The cookie may or may not be gone; reloading settles it either way.
    }
    // Reload rather than switching a flag: it is the only way to be sure no
    // document text from the previous session is still in memory.
    window.location.href = redirectUrl ?? window.location.pathname
  }

  /** Called once at startup, before anything else talks to the API. */
  async function initialize(): Promise<void> {
    problem.value = takeAuthErrorFromUrl()
    setUnauthorizedHandler(markSignedOut)
    await fetchSession()
  }

  return {
    enabled,
    authenticated,
    user,
    loginUrl,
    ready,
    signingOut,
    problem,
    blocked,
    initialize,
    fetchSession,
    markSignedOut,
    signIn,
    signOut,
  }
})
