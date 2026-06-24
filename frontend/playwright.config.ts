import { defineConfig } from '@playwright/test'

export default defineConfig({
  timeout: 15000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    screenshot: 'on',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5173',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 120000,
  },
})
