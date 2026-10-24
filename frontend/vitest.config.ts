import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// Unit tests for pure frontend helpers plus component mount smoke tests. The
// e2e suite (Playwright) covers the critical app flows; vitest covers small
// pure functions and setup-order regressions that don't need a running
// backend. happy-dom provides `window` for modules that read it at import
// time (e.g. the Tauri detection in api/client); the vue plugin lets tests
// import .vue single-file components.
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.test.ts'],
  },
})
