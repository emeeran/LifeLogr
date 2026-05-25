<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { entriesApi } from '../../../api/entries'
import { useEntriesStore } from '../../../stores/entries'
import { getSettings } from '../../../api/settings'
import type { AppSettings } from '../../../api/settings'
import {
  AlertTriangle, Loader, Info as InfoIcon
} from 'lucide-vue-next'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

const entriesStore = useEntriesStore()

// ── About / App Info ──
const appSettings = ref<AppSettings | null>(null)
async function loadAppSettings() {
  try { appSettings.value = await getSettings() } catch { /* ignore */ }
}

// ── Reset ──
const showResetConfirm = ref(false)
const resetConfirmText = ref('')
const resetting = ref(false)

async function handleReset() {
  resetting.value = true
  try { await entriesApi.resetDatabase(); entriesStore.refreshAll(); emit('toast', 'success', 'Database cleared'); showResetConfirm.value = false; resetConfirmText.value = '' }
  catch (e: unknown) { emit('toast', 'error', `Reset failed: ${errMsg(e)}`) }
  finally { resetting.value = false }
}

onMounted(() => {
  loadAppSettings()
})
</script>

<template>
  <!-- About -->
  <section>
    <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1 mb-1">
      <InfoIcon :size="11" /> About
    </h3>
    <div class="bg-surface rounded p-3 border border-border space-y-1.5 text-center">
      <div class="text-sm font-semibold text-text-primary">{{ appSettings?.app_name ?? 'DailyByte' }}</div>
      <div class="text-[10px] text-text-muted">Version {{ appSettings?.version ?? '0.1.0' }}</div>
      <div class="text-[10px] text-text-secondary">Privacy-first, offline-first journaling for Linux</div>
      <div class="text-[10px] text-accent italic pt-1">Dedicated to my son Tariq Al Fayad</div>
      <div class="flex justify-center gap-3 pt-1">
        <a href="https://github.com/diarilinux/diarilinux" target="_blank" class="text-[10px] text-accent hover:underline">GitHub</a>
        <a href="https://github.com/diarilinux/diarilinux/issues" target="_blank" class="text-[10px] text-accent hover:underline">Report Issue</a>
        <a href="https://github.com/diarilinux/diarilinux/blob/main/LICENSE" target="_blank" class="text-[10px] text-accent hover:underline">License</a>
      </div>
    </div>
  </section>

  <!-- Danger Zone -->
  <section class="pb-2">
    <div class="bg-surface rounded p-2 border border-danger/30">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-[11px] font-medium text-danger">Reset Database</div>
          <div class="text-[10px] text-text-secondary">Delete all entries, tags, and media.</div>
        </div>
        <button class="px-2 py-0.5 rounded text-[10px] bg-danger/15 text-danger hover:bg-danger/25 cursor-pointer"
          @click="showResetConfirm = true">Reset</button>
      </div>
      <div v-if="showResetConfirm" class="mt-2 p-2 bg-danger/10 rounded border border-danger/40 space-y-1.5">
        <p class="text-[11px] text-danger font-medium flex items-center gap-1">
          <AlertTriangle :size="12" /> This cannot be undone.
        </p>
        <input v-model="resetConfirmText"
          class="w-full px-2 py-1 bg-surface border border-danger/40 rounded text-[11px] text-text-primary placeholder-text-muted outline-none focus:border-danger"
          placeholder='Type "RESET" to confirm' />
        <div class="flex items-center gap-2">
          <button class="px-3 py-0.5 rounded text-[10px] font-medium bg-danger text-white hover:bg-red-600 cursor-pointer disabled:opacity-40"
            :disabled="resetConfirmText !== 'RESET' || resetting" @click="handleReset">
            <Loader v-if="resetting" :size="9" class="animate-spin inline" />
            {{ resetting ? 'Erasing...' : 'Erase Everything' }}
          </button>
          <button class="px-2 py-0.5 rounded text-[10px] text-text-secondary cursor-pointer"
            @click="showResetConfirm = false; resetConfirmText = ''">Cancel</button>
        </div>
      </div>
    </div>
  </section>
</template>
