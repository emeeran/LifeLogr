import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: 'tests',
  timeout: 15000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    screenshot: 'on',
    trace: 'on-first-retry',
    // Playwright's browser downloader refuses unsupported host distros (e.g.
    // ubuntu26.04); fall back to the system Chrome when one is available.
    channel: process.env.PLAYWRIGHT_CHANNEL,
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5173',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 120000,
  },
})
