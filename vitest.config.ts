// Vitest config for the frontend unit suite.
//
// Kept separate from `frontend/vite.config.ts` (the build/dev config) so the
// test toolchain never leaks into the production bundle. Mirrors the `@` alias
// so specs import app code exactly the way components do.
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'frontend'),
    },
  },
  test: {
    // jsdom gives composables and stores a DOM (document, timers, lifecycle).
    environment: 'jsdom',
    // Co-locate specs next to the code they cover (utils/, composables/, …).
    include: ['frontend/**/*.{test,spec}.ts'],
    // Explicit imports from 'vitest' in every spec (no ambient globals) keeps
    // eslint and tsconfig happy without widening their `types`.
    globals: false,
    clearMocks: true,
    restoreMocks: true,
  },
})
