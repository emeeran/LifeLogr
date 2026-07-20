<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { request } from './api/client'
import { installExternalLinkInterceptor } from './utils/externalLink'
import AppShell from './components/layout/AppShell.vue'
import SplashScreen from './components/layout/SplashScreen.vue'

// The startup dedication splash shows when the memorial-title feature is on.
const memorialTitle = useLocalStorage<boolean>('lifelogr-memorial-title', true)
const showSplash = ref(false)

// Memorial audio: plays only while the dedication splash is on screen.
// Browsers block unmuted autoplay on a cold load, so we ask the local backend
// to play the bundled Garden.mp3 through the system audio device (no autoplay
// restriction there). If no player is available the backend returns
// mode:"browser" and we fall back to the in-browser <audio>, which still needs
// a click/keypress to start. Either way, audio stops the moment the splash
// dismisses — by its 10s timer, a click, or Esc.
const memorialAudio = ref<HTMLAudioElement | null>(null)
let memorialInteractCleanup: (() => void) | null = null

function stopMemorialAudio() {
  const a = memorialAudio.value
  if (a) { a.pause(); a.currentTime = 0 }
  if (memorialInteractCleanup) { memorialInteractCleanup(); memorialInteractCleanup = null }
  // Best-effort: tell the backend to stop its player too (no-op if it wasn't).
  request('/memorial/audio/stop', { method: 'POST' }).catch(() => {})
}

async function playMemorialAudio() {
  // Prefer backend-driven system audio (bypasses the browser autoplay policy).
  try {
    const data = await request<{ mode: string }>('/memorial/audio/start', { method: 'POST' })
    if (data.mode === 'system') return // backend is playing — nothing more to do
  } catch {
    /* endpoint missing/unreachable → try the in-browser fallback below */
  }
  playMemorialAudioInBrowser()
}

function playMemorialAudioInBrowser() {
  const a = memorialAudio.value
  if (!a) return
  const p = a.play()
  if (p && typeof p.then === 'function') {
    p.catch(() => {
      // Autoplay blocked: retry on the first click/keypress. If the splash
      // closes first, stopMemorialAudio removes this listener.
      memorialInteractCleanup = () => {
        window.removeEventListener('pointerdown', startOnInteract)
        window.removeEventListener('keydown', startOnInteract)
      }
      window.addEventListener('pointerdown', startOnInteract)
      window.addEventListener('keydown', startOnInteract)
    })
  }
  function startOnInteract() {
    a?.play().catch(() => {})
    if (memorialInteractCleanup) { memorialInteractCleanup(); memorialInteractCleanup = null }
  }
}

// Open external hyperlinks (http/https/mailto/tel) in the system default
// browser/handler instead of navigating the Tauri webview.
let detachExternalLinks: (() => void) | null = null

onMounted(() => {
  showSplash.value = memorialTitle.value
  if (showSplash.value) nextTick(playMemorialAudio)
  detachExternalLinks = installExternalLinkInterceptor()
})
// Stop the audio as soon as the splash is dismissed.
watch(showSplash, (v) => { if (!v) stopMemorialAudio() })
onUnmounted(() => {
  stopMemorialAudio()
  detachExternalLinks?.()
})
</script>

<template>
  <AppShell />
  <audio ref="memorialAudio" src="/Garden.mp3" preload="auto" />
  <Transition name="splash-fade">
    <SplashScreen v-if="showSplash" @done="showSplash = false" />
  </Transition>
</template>

<style>
.splash-fade-enter-active,
.splash-fade-leave-active {
  transition: opacity 0.6s ease;
}
.splash-fade-enter-from,
.splash-fade-leave-to {
  opacity: 0;
}
</style>
