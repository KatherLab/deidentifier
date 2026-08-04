/**
 * UI settings (persisted in localStorage). Only presentation preferences live
 * here — never any document content (privacy rule, see stores/session.ts).
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

const EXPERT_MODE_KEY = 'expertMode'

function readExpertMode(): boolean {
  try {
    return localStorage.getItem(EXPERT_MODE_KEY) === '1'
  } catch {
    return false
  }
}

export const useSettingsStore = defineStore('settings', () => {
  /**
   * Expert mode: shows diagnostic details (detector, confidence, timings,
   * character offsets, warning categories) and unlocks the free multi-panel
   * combination on the result view. Off = the calm default UI.
   */
  const expertMode = ref(readExpertMode())

  function setExpertMode(value: boolean): void {
    expertMode.value = value
    try {
      localStorage.setItem(EXPERT_MODE_KEY, value ? '1' : '0')
    } catch {
      /* localStorage unavailable — the preference just won't persist */
    }
  }

  return { expertMode, setExpertMode }
})
