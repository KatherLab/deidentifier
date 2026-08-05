import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'

const frontendDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, frontendDir, '')

  // Backend URL - can be overridden via env var VITE_BACKEND_URL
  const backendUrl = env.VITE_BACKEND_URL || 'http://localhost:8000'

  return {
    plugins: [vue(), tailwindcss()],
    // vue-i18n feature flags: strip the legacy/devtools code and silence the
    // "runtime-only build" warnings. The alias below pulls in the full
    // (esm-bundler) build so message strings compile at runtime.
    define: {
      __VUE_I18N_FULL_INSTALL__: true,
      __VUE_I18N_LEGACY_API__: false,
      __INTLIFY_PROD_DEVTOOLS__: false,
    },
    resolve: {
      alias: {
        '@': frontendDir,
        'vue-i18n': 'vue-i18n/dist/vue-i18n.esm-bundler.js',
      },
    },
    root: frontendDir,
    server: {
      port: 3000,
      proxy: {
        // Proxy API requests to backend
        '/api': {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
  }
})
