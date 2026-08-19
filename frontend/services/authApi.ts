import type { AxiosResponse } from 'axios'
import { api } from '@/services/api'
import type { AuthSession, LogoutResponse } from '@/types/auth'

export const authApi = {
  /** Who is signed in — and whether a sign-in gate exists at all. */
  getSession(): Promise<AxiosResponse<AuthSession>> {
    return api.get<AuthSession>('/auth/session')
  },

  /** Ends the session here; the response says whether the provider wants a
   *  visit too (RP-initiated logout). */
  logout(): Promise<AxiosResponse<LogoutResponse>> {
    return api.post<LogoutResponse>('/auth/logout')
  },
}
