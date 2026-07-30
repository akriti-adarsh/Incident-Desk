import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      // The 70% floor applies to logic: the client, stores, and lib helpers.
      // Components and the WebSocket hook are exercised by the Playwright E2E
      // suite and the backend's cross-instance tests, not by unit coverage.
      include: ['src/api/client.ts', 'src/lib/**/*.ts', 'src/store/**/*.ts'],
      exclude: ['src/lib/useRealtime.ts', 'src/lib/useOrgContext.ts'],
      thresholds: { lines: 70, functions: 70, statements: 70 },
    },
  },
})
