import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { visualizer } from 'rollup-plugin-visualizer'
import { defineConfig } from 'vite'

// Bundle-composition report, gated so it never slows a normal build.
// Emit into the gitignored local/ dir: `npm run build:analyze` → local/bundle-stats.html
const analyze = process.env.VITE_BUNDLE_ANALYZE === '1'

export default defineConfig(() => ({
  plugins: [
    vue(),
    tailwindcss(),
    ...(analyze
      ? [
          visualizer({
            filename: fileURLToPath(new URL('../local/bundle-stats.html', import.meta.url)),
            open: false,
            gzipSize: true,
          }),
        ]
      : []),
  ],
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
    target: 'es2022',
    minify: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Stable vendor libs split into named chunks. In Tauri these load from
          // local disk (near-free), so splitting aids cacheability and keeps the
          // entry chunk small without a network penalty.
          if (
            id.includes('node_modules/vue/') ||
            id.includes('node_modules/@vue/') ||
            id.includes('node_modules/vue-router/') ||
            id.includes('node_modules/pinia/')
          ) {
            return 'vendor-vue'
          }
          if (id.includes('node_modules/@tauri-apps/')) return 'vendor-tauri'
          if (id.includes('node_modules/marked/') || id.includes('node_modules/dompurify/')) {
            return 'vendor-markdown'
          }
          if (id.includes('node_modules/lucide-vue-next/')) return 'vendor-icons'
        },
      },
    },
  },
}))
