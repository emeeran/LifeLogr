<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { entriesApi } from '../../../api/entries'
import { useEntriesStore } from '../../../stores/entries'
import { getSettings } from '../../../api/settings'
import type { AppSettings } from '../../../api/settings'
import { APP_VERSION } from '../../../version'
import { useUpdateChecker, REPO_URL } from '../../../composables/useUpdateChecker'
import {
  AlertTriangle, Loader, Info as InfoIcon,
  ShieldCheck, WifiOff, Cloud, Mic, Sparkles, Github,
  RefreshCw, DownloadCloud, CheckCircle2, ExternalLink,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import MemorialTribute from '../MemorialTribute.vue'
import memorialImg from '../../../assets/tariq-memorial.jpg'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

function errMsg(e: unknown): string { return e instanceof Error ? e.message : String(e) }

const entriesStore = useEntriesStore()

// `version` from the backend is informational; the authoritative version
// shown in the UI is the build-time APP_VERSION (always matches the .deb).
const appSettings = ref<AppSettings | null>(null)
async function loadAppSettings() {
  try { appSettings.value = await getSettings() } catch { /* ignore */ }
}

const links = [
  { label: 'GitHub', href: REPO_URL, icon: Github },
  { label: 'Report Issue', href: `${REPO_URL}/issues`, icon: AlertTriangle },
  { label: 'License', href: `${REPO_URL}/blob/main/LICENSE`, icon: ShieldCheck },
]

// Update checker — shared affordance with the "What's New" tab.
const { status: updateStatus, check: checkForUpdates } = useUpdateChecker()
async function handleCheck() {
  await checkForUpdates()
  const s = updateStatus.value
  if (s.kind === 'available') emit('toast', 'info', `LifeLogr ${s.latest} is available`)
  else if (s.kind === 'up-to-date') emit('toast', 'success', `You're on the latest version (${APP_VERSION})`)
  else if (s.kind === 'offline') emit('toast', 'error', 'Could not check for updates (offline)')
}

const features = [
  { icon: ShieldCheck, label: 'Privacy-first', sub: 'Your data, your device' },
  { icon: WifiOff, label: 'Offline-first', sub: 'Works without a network' },
  { icon: Sparkles, label: 'Local AI', sub: 'Ollama-powered insights' },
  { icon: Mic, label: 'Voice & OCR', sub: 'Whisper + Tesseract' },
  { icon: Cloud, label: 'Encrypted Sync', sub: 'End-to-end backups' },
]

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
  <!-- ── App Identity Hero ─────────────────────────────────────────── -->
  <section class="relative overflow-hidden rounded-lg border border-border bg-surface">
    <!-- soft accent wash -->
    <div class="pointer-events-none absolute inset-0 opacity-[0.06]"
      style="background: radial-gradient(60% 80% at 50% 0%, var(--color-accent) 0%, transparent 70%);" />
    <div class="relative px-6 pt-8 pb-6 flex flex-col items-center text-center">
      <!-- Brand mark: dark accent tile + white-invert filter so the gray logo pops. -->
      <div class="w-20 h-20 rounded-2xl flex items-center justify-center bg-accent shadow-md overflow-hidden">
        <img src="/logo.png" alt="LifeLogr logo" class="logo-mark w-12 h-12 object-contain" />
      </div>

      <h2 class="mt-3.5 text-xl font-semibold text-text-primary tracking-tight">LifeLogr</h2>
      <p class="text-[12px] text-text-secondary mt-0.5">Privacy-first, offline-first journaling for Linux</p>

      <!-- version badge: build-time APP_VERSION is authoritative -->
      <div class="mt-3 flex flex-col items-center gap-2">
        <div class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-accent/30 bg-accent/10">
          <span class="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          <span class="text-[11px] font-medium text-accent">v{{ APP_VERSION }}</span>
          <span v-if="appSettings && appSettings.version && appSettings.version !== APP_VERSION"
            class="text-[10px] text-text-muted">(backend {{ appSettings.version }})</span>
        </div>

        <!-- update-check affordance -->
        <div class="flex items-center gap-2">
          <button @click="handleCheck"
            :disabled="updateStatus.kind === 'checking'"
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium bg-white border border-border text-text-secondary hover:border-accent/50 hover:text-accent disabled:opacity-50 cursor-pointer transition-colors">
            <RefreshCw :size="11" :class="{ 'animate-spin': updateStatus.kind === 'checking' }" />
            {{ updateStatus.kind === 'checking' ? 'Checking…' : 'Check for updates' }}
          </button>
          <!-- inline result indicators -->
          <span v-if="updateStatus.kind === 'up-to-date'"
            class="inline-flex items-center gap-1 text-[10.5px] text-green-600 font-medium">
            <CheckCircle2 :size="12" /> Up to date
          </span>
          <span v-else-if="updateStatus.kind === 'offline'"
            class="inline-flex items-center gap-1 text-[10.5px] text-amber-600 font-medium">
            <WifiOff :size="12" /> Offline
          </span>
          <a v-else-if="updateStatus.kind === 'available'" :href="updateStatus.url"
            target="_blank" rel="noopener noreferrer"
            class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover transition-colors animate-pulse">
            <DownloadCloud :size="12" /> {{ updateStatus.latest }}
            <ExternalLink :size="10" />
          </a>
        </div>
      </div>

      <!-- feature highlights -->
      <div class="mt-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 w-full max-w-2xl">
        <div v-for="f in features" :key="f.label"
          class="flex flex-col items-center gap-1 px-2 py-2.5 rounded-md bg-white/60 border border-border/60">
          <component :is="f.icon" :size="15" class="text-accent" />
          <div class="text-[11px] font-medium text-text-primary leading-tight">{{ f.label }}</div>
          <div class="text-[9.5px] text-text-muted leading-tight text-center">{{ f.sub }}</div>
        </div>
      </div>

      <!-- links -->
      <div class="mt-5 flex flex-wrap items-center justify-center gap-2">
        <a v-for="l in links" :key="l.label" :href="l.href" target="_blank" rel="noopener noreferrer"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium text-text-secondary bg-white/70 border border-border hover:border-accent/50 hover:text-accent transition-colors">
          <component :is="l.icon" :size="12" />
          {{ l.label }}
        </a>
      </div>
    </div>
  </section>

  <!-- ── Dedication / In Loving Memory — dynamic, resizable tribute ── -->
  <MemorialTribute :image="memorialImg" />

  <!-- ── Danger Zone ───────────────────────────────────────────────── -->
  <SettingsSection title="Danger Zone" :icon="InfoIcon" description="Irreversible maintenance actions"
    card-class="p-0">
    <div class="bg-surface p-3">
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
  </SettingsSection>
</template>

<style scoped>
/* Tint the gray+alpha logo to pure white so it reads crisply on the accent tile. */
.logo-mark {
  filter: brightness(0) invert(1);
}
</style>
