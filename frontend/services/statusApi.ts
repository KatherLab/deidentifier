import type { AxiosResponse } from 'axios'
import { api } from '@/services/api'
import type { StatusResponse } from '@/types/anonymizer'

export const statusApi = {
  /** Configured detectors/endpoints + limits; flags non-local endpoints. */
  getStatus(): Promise<AxiosResponse<StatusResponse>> {
    return api.get<StatusResponse>('/status')
  },
}
