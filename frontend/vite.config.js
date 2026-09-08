import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// During real-device debugging the launcher injects the computer's current
// backend URL through DEEPTRAVEL_BACKEND_URL. Keep localhost as the safe
// default so a stale LAN address cannot turn the admin page into HTTP 502
// after the computer changes networks.
function envHost() {
  if (process.env.DEEPTRAVEL_BACKEND_URL) return ''
  try {
    const envPath = fileURLToPath(new URL('../.env', import.meta.url))
    const content = readFileSync(envPath, 'utf8')
    const match = content.match(/^APP_HOST\s*=\s*([^#\s]+)\s*$/m)
    const host = String(match?.[1] || '').trim()
    if (host && host !== '0.0.0.0' && host !== '::') return host
  } catch {
    // Fall back to loopback when the package is used without a root .env.
  }
  return '127.0.0.1'
}

const backendTarget = process.env.DEEPTRAVEL_BACKEND_URL || `http://${envHost()}:8000`

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // Keep this overrideable for deployments where the API is remote.
      '/api': {
        target: backendTarget,
      },
      '/health': {
        target: backendTarget,
      },
    },
  },
})
