<script setup lang="ts">
import { ref, computed } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import {
  CheckCircle2, AlertTriangle, X, Info,
  Brain, Sparkles, HardDrive, Sliders, Search
} from 'lucide-vue-next'
import GeneralTab from './tabs/GeneralTab.vue'
import AITab from './tabs/AITab.vue'
import DataTab from './tabs/DataTab.vue'
import FeaturesTab from './tabs/FeaturesTab.vue'
import AboutTab from './tabs/AboutTab.vue'

// ── Tab navigation ──
const activeTab = useLocalStorage<string>('diarium-settings-tab', 'general')
const tabs = [
  { id: 'general', label: 'General', icon: Sliders },
  { id: 'ai', label: 'AI', icon: Brain },
  { id: 'data', label: 'Data', icon: HardDrive },
  { id: 'features', label: 'Features', icon: Sparkles },
  { id: 'about', label: 'About', icon: Info },
] as const

// ── Settings search ──
const searchQuery = ref('')
const searchLower = computed(() => searchQuery.value.toLowerCase().trim())

const tabKeywords: Record<string, string> = {
  general: 'appearance dark mode font family size editor autosave ocr language default title search mode hybrid keyword semantic preferences auto-tag location geotag template keyboard shortcuts',
  ai: 'ai ollama model embeddings tag suggestions sentiment analysis summarization reflection prompts writer block pull themes insights',
  data: 'storage database entries media import export deduplicate backup cloud webdav google drive mega onedrive dropbox nas sync push pull flush auto backup schedule cron',
  features: 'read aloud tts voice speed volume notifications reminders plugins marketplace system setup tesseract dependencies recording',
  about: 'about version credits github license reset database danger',
}

const filteredTabs = computed(() => {
  if (!searchLower.value) return tabs
  return tabs.filter(t => {
    const keywords = tabKeywords[t.id] ?? ''
    return t.label.toLowerCase().includes(searchLower.value) || keywords.includes(searchLower.value)
  })
})

// ── Toast ──
const toast = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error' | 'info', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="px-4 py-2.5 border-b border-border">
      <h2 class="text-xs font-semibold text-text-primary tracking-wide">Settings</h2>
    </div>

    <!-- Tab sidebar + content panel -->
    <div class="flex flex-1 min-h-0">

      <!-- Vertical tab sidebar -->
      <nav class="w-40 shrink-0 border-r border-border py-2 px-2 space-y-0.5 overflow-y-auto">
        <!-- Search input -->
        <div class="mb-2">
          <div class="flex items-center gap-1.5 bg-surface border border-border rounded-md px-2 py-1">
            <Search :size="12" class="text-text-muted shrink-0" />
            <input v-model="searchQuery" placeholder="Search..."
              class="bg-transparent text-[11px] text-text-primary outline-none w-full placeholder-text-muted" />
            <button v-if="searchQuery" @click="searchQuery = ''"
              class="text-text-muted hover:text-text-primary cursor-pointer shrink-0">
              <X :size="12" />
            </button>
          </div>
        </div>
        <button v-for="tab in filteredTabs" :key="tab.id"
          @click="activeTab = tab.id"
          class="w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-[12px] font-medium cursor-pointer transition-colors"
          :class="activeTab === tab.id
            ? 'bg-accent/15 text-accent'
            : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary'">
          <component :is="tab.icon" :size="14" />
          {{ tab.label }}
        </button>
        <div v-if="!filteredTabs.length" class="px-2 py-2 text-[11px] text-text-muted text-center">
          No matching settings.
        </div>
      </nav>

      <!-- Content panel -->
      <div class="flex-1 overflow-y-auto px-5 py-4 space-y-4">

        <GeneralTab v-if="activeTab === 'general'" @toast="showToast" />
        <AITab v-if="activeTab === 'ai'" @toast="showToast" />
        <DataTab v-if="activeTab === 'data'" @toast="showToast" />
        <FeaturesTab v-if="activeTab === 'features'" @toast="showToast" />
        <AboutTab v-if="activeTab === 'about'" @toast="showToast" />

      </div>
    </div>

    <!-- Toast -->
    <Transition name="toast">
      <div v-if="toast" class="absolute bottom-3 left-3 right-3 flex items-center gap-2 px-3 py-1.5 rounded-md border text-[12px]"
        :class="{
          'bg-green-900/80 border-green-700 text-green-200': toast.type === 'success',
          'bg-red-900/80 border-red-700 text-red-200': toast.type === 'error',
          'bg-surface border-border text-text-primary': toast.type === 'info',
        }">
        <CheckCircle2 v-if="toast.type === 'success'" :size="14" />
        <AlertTriangle v-else-if="toast.type === 'error'" :size="14" />
        <Info v-else :size="14" />
        {{ toast.message }}
        <button class="ml-auto p-0.5 cursor-pointer" @click="toast = null"><X :size="12" /></button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
</style>
