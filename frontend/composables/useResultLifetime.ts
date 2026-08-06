/**
 * Ticking view of how long the active result stays available on the server.
 *
 * One interval per mounted result view; the arithmetic lives in
 * `utils/lifetime.ts`. The deadline is absolute (epoch ms), so a tab the OS
 * suspended shows the right number the moment it wakes up instead of resuming
 * a stale count.
 */
import { computed, onUnmounted, ref, type ComputedRef } from 'vue'
import {
  formatRemaining,
  isExpired as expired,
  isExpiring as expiring,
  remainingSeconds,
} from '@/utils/lifetime'

export interface ResultLifetime {
  /** Seconds left, or null when there is no result to count down. */
  remaining: ComputedRef<number | null>
  /** `m:ss` for display. */
  formatted: ComputedRef<string>
  /** Inside the warning window — the UI offers an extension. */
  isExpiring: ComputedRef<boolean>
  /** The server no longer holds this result. */
  isExpired: ComputedRef<boolean>
}

export function useResultLifetime(expiresAt: () => number | null): ResultLifetime {
  const now = ref(Date.now())
  const timer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
  onUnmounted(() => window.clearInterval(timer))

  const remaining = computed(() => remainingSeconds(expiresAt(), now.value))
  return {
    remaining,
    formatted: computed(() => formatRemaining(remaining.value)),
    isExpiring: computed(() => expiring(remaining.value)),
    isExpired: computed(() => expired(remaining.value)),
  }
}
