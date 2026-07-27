import { defineConfig } from 'vitest/config'

// Unit tests for pure frontend helpers. The e2e suite (Playwright) covers the
// critical app flows; vitest covers small pure functions that don't need a
// running backend. happy-dom provides `window` for modules that read it at
// import time (e.g. the Tauri detection in api/client).
export default defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
  },
})
