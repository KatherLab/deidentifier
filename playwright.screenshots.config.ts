import { defineConfig, devices } from '@playwright/test'

// Documentation-screenshot harness. Boots the same servers as the e2e smoke
// (fake OpenAI-compatible LLM on 9099, FastAPI backend on 8000 via
// backend/.env.e2e) but puts Vite on 3100, walks the product workflow with the
// synthetic fixtures from backend/tests/files, and captures PNGs into
// docs/assets/screenshots/.
//
// Run with `npm run screenshots`. Kept separate from playwright.config.ts so
// the smoke test stays fast and the screenshot run can pin a viewport, retina
// scale, and light theme without affecting CI.
const CI = !!process.env.CI

export default defineConfig({
  testDir: './e2e/screenshots',
  // Capturing every documented screen touches the whole app; give it room.
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: CI,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:3100',
    // Fixed, retina-crisp desktop frame for consistent docs images.
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    // Force light mode regardless of OS preference (the docs are light-only).
    colorScheme: 'light',
    // The documented screens are German; the app otherwise follows the
    // browser language (see frontend/i18n).
    locale: 'de-DE',
    screenshot: 'off',
    trace: 'off',
    // Cap every action so one bad selector can't consume the whole budget.
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },
  // `channel: 'chromium'` selects the new headless mode, which ships the
  // built-in PDF viewer — the default headless shell renders <iframe> PDFs as
  // a blank panel, and the redacted-PDF preview is one of the screens we
  // document.
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], channel: 'chromium' } }],
  webServer: [
    {
      command: 'node e2e/support/fake-llm.mjs',
      port: 9099,
      reuseExistingServer: false,
      env: { FAKE_LLM_PORT: '9099' },
    },
    {
      command: 'uv run uvicorn backend.src.main:app --host 127.0.0.1 --port 8000',
      port: 8000,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { ENV_PATH: 'backend/.env.e2e' },
    },
    {
      command: 'npm run dev -- --port 3100 --strictPort',
      url: 'http://localhost:3100',
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
  ],
})
