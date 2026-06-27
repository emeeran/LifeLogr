<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import AppShell from './components/layout/AppShell.vue'
import SplashScreen from './components/layout/SplashScreen.vue'

// The startup dedication splash shows when the memorial-title feature is on.
const memorialTitle = useLocalStorage<boolean>('lifelogr-memorial-title', true)
const showSplash = ref(false)
onMounted(() => { showSplash.value = memorialTitle.value })
</script>

<template>
  <AppShell />
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
