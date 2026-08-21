/**
 * UI settings (persisted in localStorage). Only presentation preferences live
 * here — never any document content (privacy rule, see stores/session.ts).
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

const EXPERT_MODE_KEY = 'expertMode'
const KEEP_FILENAMES_KEY = 'keepFilenames'
const REDACTION_BARS_KEY = 'redactionBars'

function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function writeFlag(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* localStorage unavailable — the preference just won't persist */
  }
}

export const useSettingsStore = defineStore('settings', () => {
  /**
   * Expert mode: shows diagnostic details (detector, confidence, timings,
   * character offsets, warning categories) and unlocks the free multi-panel
   * combination on the result view. Off = the calm default UI.
   */
  const expertMode = ref(readFlag(EXPERT_MODE_KEY))

  function setExpertMode(value: boolean): void {
    expertMode.value = value
    writeFlag(EXPERT_MODE_KEY, value)
  }

  /**
   * Keep the ORIGINAL filenames on export instead of "anonymisiert.*".
   * Opt-in: filenames themselves frequently contain PII (patient names), so
   * the safe default renames everything.
   */
  const keepFilenames = ref(readFlag(KEEP_FILENAMES_KEY))

  function setKeepFilenames(value: boolean): void {
    keepFilenames.value = value
    writeFlag(KEEP_FILENAMES_KEY, value)
  }

  /**
   * Black bars instead of readable placeholders in a SCANNED document's
   * redacted PDF. Off by default: the placeholders say what was removed and
   * which person a tag refers to, which is worth more than looking like the
   * native export — but a site that hands the file on often wants the bars.
   */
  const redactionBars = ref(readFlag(REDACTION_BARS_KEY))

  function setRedactionBars(value: boolean): void {
    redactionBars.value = value
    writeFlag(REDACTION_BARS_KEY, value)
  }

  return {
    expertMode,
    setExpertMode,
    keepFilenames,
    setKeepFilenames,
    redactionBars,
    setRedactionBars,
  }
})
