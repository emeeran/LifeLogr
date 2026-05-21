import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => ({
  plugins: [vue(), tailwindcss()],
  define: {
    'import.meta.env.VITE_PLATFORM': JSON.stringify(process.env.VITE_PLATFORM || 'web'),
  },
  server: {
    proxy: process.env.VITE_PLATFORM === 'capacitor' ? undefined : {
      '/api': {
        target: `http://localhost:${process.env.VITE_BACKEND_PORT || 8000}`,
        timeout: 300000,
      },
      '/health': `http://localhost:${process.env.VITE_BACKEND_PORT || 8000}`,
    },
  },
  build: {
    minify: mode === 'production',
    sourcemap: mode !== 'production',
  },
}))
