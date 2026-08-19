/**
 * The optional sign-in gate (backend `schemas/auth.py`).
 *
 * The app has no user accounts — `AuthUser` exists so the header can say who
 * is signed in, and for nothing else. Everyone who gets past the gate sees the
 * same application.
 */

export interface AuthUser {
  name: string
  email: string
}

export interface AuthSession {
  /** False when no gate is configured — then `authenticated` is always true. */
  enabled: boolean
  authenticated: boolean
  user: AuthUser | null
  /** Where the browser goes to start a sign-in; empty when the gate is off. */
  login_url: string
}

export interface LogoutResponse {
  /** Set when the identity provider should end its session too. */
  redirect_url: string | null
}

/** The `?auth_error=` codes the backend redirects back with. */
export type AuthErrorCode = 'denied' | 'state' | 'provider' | 'token' | 'identity'
