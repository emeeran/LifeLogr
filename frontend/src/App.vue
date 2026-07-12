<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import AppShell from './components/layout/AppShell.vue'
import SplashScreen from './components/layout/SplashScreen.vue'

// The startup dedication splash shows when the memorial-title feature is on.
const memorialTitle = useLocalStorage<boolean>('lifelogr-memorial-title', true)
const showSplash = ref(false)

// Memorial audio: plays once at startup when the dedication splash displays.
// Browsers block unmuted autoplay before the first interaction, so if the
// immediate play() is rejected we wait for the first click/keypress.
const memorialAudio = ref<HTMLAudioElement | null>(null)
let memorialInteractCleanup: (() => void) | null = null

function playMemorialAudio() {
  const a = memorialAudio.value
  if (!a) return
  const p = a.play()
  if (p && typeof p.then === 'function') {
    p.catch(() => {
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

onMounted(() => {
  showSplash.value = memorialTitle.value
  if (showSplash.value) nextTick(playMemorialAudio)
})
onUnmounted(() => { if (memorialInteractCleanup) memorialInteractCleanup() })
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
