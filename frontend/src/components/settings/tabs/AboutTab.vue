<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { entriesApi } from '../../../api/entries'
import { useEntriesStore } from '../../../stores/entries'
import { getSettings } from '../../../api/settings'
import type { AppSettings } from '../../../api/settings'
import { APP_VERSION } from '../../../version'
import {
  AlertTriangle, Loader, Info as InfoIcon, Heart
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import memorialImg from '../../../assets/tariq-memorial.jpg'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

const entriesStore = useEntriesStore()

const appSettings = ref<AppSettings | null>(null)
async function loadAppSettings() {
  try { appSettings.value = await getSettings() } catch { /* ignore */ }
}

const showResetConfirm = ref(false)
const resetConfirmText = ref('')
const resetting = ref(false)

async function handleReset() {
  resetting.value = true
  try { await entriesApi.resetDatabase(); entriesStore.refreshAll(); emit('toast', 'success', 'Database cleared'); showResetConfirm.value = false; resetConfirmText.value = '' }
  catch (e: unknown) { emit('toast', 'error', `Reset failed: ${errMsg(e)}`) }
  finally { resetting.value = false }
}

onMounted(() => { loadAppSettings() })
</script>

<template>
  <SettingsSection title="About" :icon="InfoIcon" description="App information and credits" card-class="p-0 overflow-hidden">
    <div class="flex items-stretch min-h-[320px]">
      <!-- Left half: app info -->
      <div class="flex-1 p-6 flex flex-col justify-center space-y-2.5 text-center">
        <div class="text-lg font-semibold text-text-primary">LifeLogr</div>
        <div class="text-[11px] text-text-muted">Version {{ appSettings?.version ?? APP_VERSION }}</div>
        <div class="text-[12px] text-text-secondary">Privacy-first, offline-first journaling for Linux</div>
        <div class="flex items-center justify-center gap-1 text-[11px] text-accent/80 italic pt-1">
          <Heart :size="11" /> Dedicated to my son Tariq Al Fayad
        </div>
        <div class="flex justify-center gap-4 pt-2">
          <a href="https://github.com/lifelogr/lifelogr" target="_blank" class="text-[11px] text-accent hover:underline">GitHub</a>
          <a href="https://github.com/lifelogr/lifelogr/issues" target="_blank" class="text-[11px] text-accent hover:underline">Report Issue</a>
          <a href="https://github.com/lifelogr/lifelogr/blob/main/LICENSE" target="_blank" class="text-[11px] text-accent hover:underline">License</a>
        </div>
      </div>
      <!-- Right half: memorial, fills the half -->
      <div class="relative shrink-0 w-1/2">
        <img :src="memorialImg" alt="In Loving Remembrance — Tariq Al Fayad (1997–2020)"
          class="absolute inset-0 w-full h-full object-cover" />
        <div class="absolute bottom-0 inset-x-0 px-2 py-1.5 text-center text-[10px] text-white italic bg-gradient-to-t from-black/70 to-transparent">
          In Loving Remembrance — Tariq Al Fayad
        </div>
      </div>
    </div>
  </SettingsSection>

  <!-- Danger Zone -->
  <section class="pb-2">
    <div class="bg-surface rounded-md p-3 border border-danger/30">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-[12px] font-medium text-danger">Reset Database</div>
          <div class="text-[11px] text-text-secondary">Delete all entries, tags, and media.</div>
        </div>
        <button class="px-2.5 py-1 rounded-md text-[11px] font-medium bg-danger/15 text-danger hover:bg-danger/25 cursor-pointer transition-colors"
          @click="showResetConfirm = true">Reset</button>
      </div>
      <div v-if="showResetConfirm" class="mt-2.5 p-2.5 bg-danger/10 rounded-md border border-danger/40 space-y-2">
        <p class="text-[12px] text-danger font-medium flex items-center gap-1.5">
          <AlertTriangle :size="12" /> This cannot be undone.
        </p>
        <input v-model="resetConfirmText"
          class="w-full px-2 py-1 bg-surface border border-danger/40 rounded-md text-[12px] text-text-primary placeholder-text-muted outline-none focus:border-danger transition-colors"
          placeholder='Type "RESET" to confirm' />
        <div class="flex items-center gap-2">
          <button class="px-3 py-0.5 rounded-md text-[11px] font-medium bg-danger text-white hover:bg-red-600 cursor-pointer disabled:opacity-40 transition-colors"
            :disabled="resetConfirmText !== 'RESET' || resetting" @click="handleReset">
            <Loader v-if="resetting" :size="10" class="animate-spin inline" />
            {{ resetting ? 'Erasing...' : 'Erase Everything' }}
          </button>
          <button class="px-2 py-0.5 rounded-md text-[11px] text-text-secondary cursor-pointer hover:text-text-primary transition-colors"
            @click="showResetConfirm = false; resetConfirmText = ''">Cancel</button>
        </div>
      </div>
    </div>
  </section>
</template>
