import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.lifelogr.app',
  appName: 'LifeLogr',
  webDir: '../frontend/dist',
  server: {
    // In dev, proxy API calls to the local backend
    url: process.env.CAPACITOR_DEV_URL,
    cleartext: true,
  },
  plugins: {
    CapacitorSQLite: {
      mode: 'no-encryption',
    },
  },
}

export default config
