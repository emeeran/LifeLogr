import { defineConfig } from '@playwright/test'

export default defineConfig({
  timeout: 15000,
  use: {
    baseURL: 'http://localhost:5173',
    screenshot: 'on',
    trace: 'on-first-retry',
  },
})
