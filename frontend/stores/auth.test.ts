import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { authApi } from '@/services/authApi'
import { notifyUnauthorized } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { AuthSession } from '@/types/auth'

function sessionResponse(overrides: Partial<AuthSession> = {}) {
  return {
    data: {
      enabled: true,
      authenticated: true,
      user: { name: 'Dr. Müller', email: 'mueller@example.org' },
      login_url: 'https://deid.example.org/api/v1/auth/login',
      ...overrides,
    } as AuthSession,
  }
}

/** jsdom forbids assigning window.location; replace it wholesale instead. */
function stubLocation(): { href: string; pathname: string; search: string } {
  const location = { href: 'https://deid.example.org/', pathname: '/', search: '' }
  Object.defineProperty(window, 'location', { value: location, writable: true })
  return location
}

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    stubLocation()
    vi.spyOn(window.history, 'replaceState').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not block anything when no gate is configured', async () => {
    vi.spyOn(authApi, 'getSession').mockResolvedValue(
      sessionResponse({ enabled: false, user: null, login_url: '' }) as never,
    )
    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.enabled).toBe(false)
    expect(auth.blocked).toBe(false)
    expect(auth.ready).toBe(true)
  })

  it('blocks the app when a gate is configured and nobody is signed in', async () => {
    vi.spyOn(authApi, 'getSession').mockResolvedValue(
      sessionResponse({ authenticated: false, user: null }) as never,
    )
    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.blocked).toBe(true)
  })

  it('reports who is signed in', async () => {
    vi.spyOn(authApi, 'getSession').mockResolvedValue(sessionResponse() as never)
    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.blocked).toBe(false)
    expect(auth.user?.name).toBe('Dr. Müller')
  })

  // An unreachable backend is not the same as being locked out — showing a
  // sign-in screen then would hide the real "server not reachable" error.
  it('stays out of the way when the session route cannot be reached', async () => {
    vi.spyOn(authApi, 'getSession').mockRejectedValue(new Error('offline'))
    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.blocked).toBe(false)
    expect(auth.ready).toBe(true)
  })

  it('shows the sign-in screen again when a 401 arrives mid-session', async () => {
    vi.spyOn(authApi, 'getSession').mockResolvedValue(sessionResponse() as never)
    const auth = useAuthStore()
    await auth.initialize()

    notifyUnauthorized()

    expect(auth.blocked).toBe(true)
    expect(auth.problem).toBe('expired')
    expect(auth.user).toBeNull()
  })

  it('ignores a 401 when there is no gate at all', async () => {
    vi.spyOn(authApi, 'getSession').mockResolvedValue(sessionResponse({ enabled: false }) as never)
    const auth = useAuthStore()
    await auth.initialize()

    notifyUnauthorized()

    expect(auth.blocked).toBe(false)
    expect(auth.problem).toBeNull()
  })

  it('picks up a failed sign-in from the URL and clears it', async () => {
    const location = stubLocation()
    location.search = '?auth_error=denied'
    location.href = 'https://deid.example.org/?auth_error=denied'
    vi.spyOn(authApi, 'getSession').mockResolvedValue(
      sessionResponse({ authenticated: false, user: null }) as never,
    )
    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.problem).toBe('denied')
    // Cleared from the address bar, or a reload would replay a stale failure.
    expect(window.history.replaceState).toHaveBeenCalledWith({}, '', 'https://deid.example.org/')
  })

  it('maps an unknown error code to the generic failure', async () => {
    const location = stubLocation()
    location.search = '?auth_error=something-new'
    location.href = 'https://deid.example.org/?auth_error=something-new'
    vi.spyOn(authApi, 'getSession').mockResolvedValue(
      sessionResponse({ authenticated: false, user: null }) as never,
    )
    const auth = useAuthStore()
    await auth.initialize()

    expect(auth.problem).toBe('unknown')
  })

  it('sends the browser to the provider to sign in', async () => {
    const location = stubLocation()
    vi.spyOn(authApi, 'getSession').mockResolvedValue(
      sessionResponse({ authenticated: false, user: null }) as never,
    )
    const auth = useAuthStore()
    await auth.initialize()
    auth.signIn()

    expect(location.href).toBe('https://deid.example.org/api/v1/auth/login')
  })

  it('reloads after signing out so no document text survives it', async () => {
    const location = stubLocation()
    vi.spyOn(authApi, 'getSession').mockResolvedValue(sessionResponse() as never)
    vi.spyOn(authApi, 'logout').mockResolvedValue({ data: { redirect_url: null } } as never)
    const auth = useAuthStore()
    await auth.initialize()
    await auth.signOut()

    expect(location.href).toBe('/')
  })

  it('follows the provider to its own sign-out page when it asks for one', async () => {
    const location = stubLocation()
    vi.spyOn(authApi, 'getSession').mockResolvedValue(sessionResponse() as never)
    vi.spyOn(authApi, 'logout').mockResolvedValue({
      data: { redirect_url: 'https://idp.example.org/logout' },
    } as never)
    const auth = useAuthStore()
    await auth.initialize()
    await auth.signOut()

    expect(location.href).toBe('https://idp.example.org/logout')
  })

  // Signing out has to end locally even if the API call does not come back.
  it('still leaves when the sign-out request fails', async () => {
    const location = stubLocation()
    vi.spyOn(authApi, 'getSession').mockResolvedValue(sessionResponse() as never)
    vi.spyOn(authApi, 'logout').mockRejectedValue(new Error('offline'))
    const auth = useAuthStore()
    await auth.initialize()
    await auth.signOut()

    expect(location.href).toBe('/')
  })
})
