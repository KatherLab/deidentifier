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
    resolve: {
      alias: {
        '@': frontendDir,
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
