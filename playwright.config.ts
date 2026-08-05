import { defineConfig, devices } from '@playwright/test'

// Playwright e2e smoke config. Boots two servers: a deterministic fake
// OpenAI-compatible LLM (9099) and the FastAPI backend (8000, configured via
// backend/.env.e2e), plus the Vite dev server (3000).
//
// frontend/services/api.ts hardcodes http://localhost:8000/api/v1 in dev mode,
// so the backend must listen on 8000 and its CORS must allow the Vite origin
// (both are set in backend/.env.e2e).
//
// Nothing is persisted server-side, so — unlike llmaixweb — there is no state
// to reset between runs.
const CI = !!process.env.CI

// Vite's port. Overridable because `reuseExistingServer` (below) will happily
// adopt whatever already listens on 3000 — including an unrelated dev server —
// and then test the wrong app. Only 3000 and 3100 are CORS-allowed in
// backend/.env.e2e, so those are the two useful values.
const PORT = process.env.E2E_PORT ?? '3000'

export default defineConfig({
  testDir: './e2e/tests',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    // The UI language follows the browser (see frontend/i18n); pin German so
    // the assertions below stay stable regardless of the runner's locale.
    locale: 'de-DE',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'node e2e/support/fake-llm.mjs',
      port: 9099,
      // e2e-specific server: never reuse, so a stale process can't mask changes.
      reuseExistingServer: false,
      env: { FAKE_LLM_PORT: '9099' },
    },
    {
      command: 'uv run uvicorn backend.src.main:app --host 127.0.0.1 --port 8000',
      port: 8000,
      // Never reuse a developer's backend: it may point at real endpoints.
      reuseExistingServer: false,
      timeout: 120_000,
      env: { ENV_PATH: 'backend/.env.e2e' },
    },
    {
      command: `npm run dev -- --port ${PORT} --strictPort`,
      url: `http://localhost:${PORT}`,
      // The dev server is the same app regardless of run; reuse it locally for
      // faster iteration, but always start fresh in CI.
      reuseExistingServer: !CI,
      timeout: 120_000,
    },
  ],
})
