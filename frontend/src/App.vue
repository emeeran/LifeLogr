<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { installExternalLinkInterceptor } from './utils/externalLink'
import AppShell from './components/layout/AppShell.vue'
import ToasterHost from './components/common/ToasterHost.vue'
import SplashScreen from './components/layout/SplashScreen.vue'
import SystemHealthBanner from './components/common/SystemHealthBanner.vue'
import { useSystemHealthStore } from './stores/systemHealth'

// The startup dedication splash shows when the memorial-title feature is on.
const memorialTitle = useLocalStorage<boolean>('lifelogr-memorial-title', true)
const showSplash = ref(false)

// Startup app-integrity report → drives the dismissible health banner.
const systemHealth = useSystemHealthStore()

// Open external hyperlinks (http/https/mailto/tel) in the system default
// browser/handler instead of navigating the Tauri webview.
let detachExternalLinks: (() => void) | null = null

onMounted(() => {
  showSplash.value = memorialTitle.value
  detachExternalLinks = installExternalLinkInterceptor()
  // Fetch the startup integrity report (request() waits for the backend).
  systemHealth.load()
})
onUnmounted(() => {
  detachExternalLinks?.()
})
</script>

<template>
  <AppShell />
  <ToasterHost />
  <SystemHealthBanner />
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
