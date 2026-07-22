// composables/useToast.ts (copied from llmaixweb)

import { useToastStore } from '@/stores/toast'
import type { ToastOptions } from '@/stores/toast'

/** Return type of `useToast()`. */
export interface UseToast {
  success: (msg: string, opts?: ToastOptions) => number
  error: (msg: string, opts?: ToastOptions) => number
  warning: (msg: string, opts?: ToastOptions) => number
  info: (msg: string, opts?: ToastOptions) => number
  dismiss: (id: number) => void
  clear: () => void
}

/**
 * Toast notification composable.
 *
 * Works from any context — including plain modules — because the backing
 * state lives in a Pinia store rather than relying on `getCurrentInstance()`.
 *
 * @returns toast methods backed by the toast store.
 */
export function useToast(): UseToast {
  const store = useToastStore()

  return {
    success: (msg, opts) => store.add(msg, { ...opts, type: 'success' }),
    error: (msg, opts) => store.add(msg, { ...opts, type: 'error' }),
    warning: (msg, opts) => store.add(msg, { ...opts, type: 'warning' }),
    info: (msg, opts) => store.add(msg, { ...opts, type: 'info' }),
    dismiss: (id) => store.dismiss(id),
    clear: () => store.clear(),
  }
}
