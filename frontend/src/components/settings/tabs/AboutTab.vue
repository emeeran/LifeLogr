<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { entriesApi } from '../../../api/entries'
import { useEntriesStore } from '../../../stores/entries'
import { getSettings } from '../../../api/settings'
import type { AppSettings } from '../../../api/settings'
import { APP_VERSION } from '../../../version'
import {
  REPO_URL,
  useUpdateChecker,
} from '../../../composables/useUpdateChecker'
import {
  AlertTriangle,
  Loader,
  Info as InfoIcon,
  ShieldCheck,
  WifiOff,
  Cloud,
  Mic,
  Sparkles,
  Github,
  Newspaper,
  RefreshCw,
  Wrench,
  MonitorCheck,
  CheckCircle2,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import UpdateStatus from '../shared/UpdateStatus.vue'
import SButton from '../shared/SButton.vue'
import ToggleSwitch from '../shared/ToggleSwitch.vue'
import AccordionItem from '../shared/AccordionItem.vue'

// Bake the changelog into the bundle — always offline-available.
import changelogRaw from '../../../../../CHANGELOG.md?raw'
import { errMsg } from '../../../utils/errMsg.ts'

const emit = defineEmits<{
  toast: [type: 'success' | 'error' | 'info', message: string]
}>()

const entriesStore = useEntriesStore()
const { autoCheckEnabled } = useUpdateChecker()
const appSettings = ref<AppSettings | null>(null)
async function loadAppSettings() {
  try {
    appSettings.value = await getSettings()
  } catch {
    /* ignore */
  }
}

const links = [
  { label: 'GitHub', href: REPO_URL, icon: Github },
  { label: 'Report Issue', href: `${REPO_URL}/issues`, icon: AlertTriangle },
  {
    label: 'License',
    href: `${REPO_URL}/blob/main/LICENSE`,
    icon: ShieldCheck,
  },
]

function onResult(
  kind: 'available' | 'up-to-date' | 'offline',
  latest?: string,
) {
  if (kind === 'available')
    emit('toast', 'info', `LifeLogr ${latest} is available`)
  else if (kind === 'up-to-date')
    emit('toast', 'success', `You're on the latest version`)
  else if (kind === 'offline')
    emit('toast', 'error', 'Could not check for updates (offline)')
}

const features = [
  { icon: ShieldCheck, label: 'Privacy-first', sub: 'Your data, your device' },
  { icon: WifiOff, label: 'Offline-first', sub: 'Works without a network' },
  { icon: Sparkles, label: 'Local AI', sub: 'Ollama-powered insights' },
  { icon: Mic, label: 'Voice & OCR', sub: 'Recording + Tesseract' },
  { icon: Cloud, label: 'Encrypted Sync', sub: 'End-to-end backups' },
]

// ── System Setup (Tauri desktop only) ──
const isTauri = !!(window as any).__TAURI_INTERNALS__
const depsStatus = ref<{
  ollama: boolean
  gst_plugins_bad: boolean
  all_installed: boolean
} | null>(null)
const setupRunning = ref(false)
const setupOutput = ref('')

async function checkSystemDeps() {
  if (!isTauri) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    depsStatus.value = (await invoke('check_deps')) as any
  } catch {
    /* not running in Tauri */
  }
}
async function runSystemSetup() {
  if (!isTauri) return
  setupRunning.value = true
  setupOutput.value = ''
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    setupOutput.value = (await invoke('run_setup')) as string
    emit('toast', 'success', 'System setup complete!')
    await checkSystemDeps()
  } catch (e: unknown) {
    setupOutput.value = errMsg(e)
    emit('toast', 'error', `Setup failed: ${errMsg(e)}`)
  } finally {
    setupRunning.value = false
  }
}

const showResetConfirm = ref(false)
const resetConfirmText = ref('')
const resetting = ref(false)

async function handleReset() {
  resetting.value = true
  try {
    await entriesApi.resetDatabase()
    entriesStore.refreshAll()
    emit('toast', 'success', 'Database cleared')
    showResetConfirm.value = false
    resetConfirmText.value = ''
  } catch (e: unknown) {
    emit('toast', 'error', `Reset failed: ${errMsg(e)}`)
  } finally {
    resetting.value = false
  }
}

/** Render only the changelog (strip the intro blurb above the first `## [`). */
const renderedChangelog = computed(() => {
  const cutAt = changelogRaw.indexOf('\n## [')
  const body = cutAt >= 0 ? changelogRaw.slice(cutAt + 1) : changelogRaw
  return DOMPurify.sanitize(marked(body) as string)
})

onMounted(() => {
  loadAppSettings()
  checkSystemDeps()
})
</script>

<template>
  <!-- App Identity Hero -->
  <section
    class="relative overflow-hidden rounded-lg border border-border bg-surface"
  >
    <div
      class="pointer-events-none absolute inset-0 opacity-[0.06]"
      style="
        background: radial-gradient(
          60% 80% at 50% 0%,
          var(--color-accent) 0%,
          transparent 70%
        );
      "
    />
    <div class="relative px-6 pt-8 pb-6 flex flex-col items-center text-center">
      <div
        class="w-20 h-20 rounded-2xl flex items-center justify-center bg-accent shadow-md overflow-hidden"
      >
        <img
          src="/logo.png"
          alt="LifeLogr logo"
          class="logo-mark w-12 h-12 object-contain"
        />
      </div>

      <h2 class="mt-3.5 text-xl font-semibold text-text-primary tracking-tight">
        LifeLogr
      </h2>
      <p class="text-[12px] text-text-secondary mt-0.5">
        Privacy-first, offline-first journaling for Linux
      </p>

      <div class="mt-3 flex flex-col items-center gap-2">
        <div
          class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-accent/30 bg-accent/10"
        >
          <span class="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          <span class="text-[11px] font-medium text-accent"
            >v{{ APP_VERSION }}</span
          >
          <span
            v-if="
              appSettings &&
              appSettings.version &&
              appSettings.version !== APP_VERSION
            "
            class="text-[10px] text-text-muted"
            >(backend {{ appSettings.version }})</span
          >
        </div>
      </div>

      <div
        class="mt-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 w-full max-w-2xl"
      >
        <div
          v-for="f in features"
          :key="f.label"
          class="flex flex-col items-center gap-1 px-2 py-2.5 rounded-md bg-white/60 border border-border/60"
        >
          <component :is="f.icon" :size="15" class="text-accent" />
          <div class="text-[11px] font-medium text-text-primary leading-tight">
            {{ f.label }}
          </div>
          <div class="text-[9.5px] text-text-muted leading-tight text-center">
            {{ f.sub }}
          </div>
        </div>
      </div>

      <div class="mt-5 flex flex-wrap items-center justify-center gap-2">
        <a
          v-for="l in links"
          :key="l.label"
          :href="l.href"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium text-text-secondary bg-white/70 border border-border hover:border-accent/50 hover:text-accent transition-colors"
        >
          <component :is="l.icon" :size="12" />
          {{ l.label }}
        </a>
      </div>
    </div>
  </section>

  <!-- Updates -->
  <SettingsSection
    title="Updates"
    :icon="RefreshCw"
    description="Check for new LifeLogr releases"
    setting-key="Updates"
  >
    <SettingRow
      label="Check for updates weekly"
      description="Quietly checks GitHub Releases once a week. Off by default."
    >
      <ToggleSwitch v-model="autoCheckEnabled" />
    </SettingRow>
    <UpdateStatus @result="onResult" />
  </SettingsSection>

  <!-- System Setup (desktop only) -->
  <AccordionItem
    v-if="isTauri"
    title="System Setup"
    :icon="Wrench"
    description="Check and install system dependencies"
  >
    <div class="space-y-2">
      <div v-if="depsStatus === null" class="text-[11px] text-text-muted">
        Checking dependencies...
      </div>
      <div
        v-else-if="depsStatus.all_installed && depsStatus.gst_plugins_bad"
        class="flex items-center gap-1.5 text-[11px] text-green-400"
      >
        <MonitorCheck :size="12" /> All system dependencies installed
      </div>
      <div v-else class="space-y-1.5">
        <div
          class="flex items-center gap-1.5 text-[11px]"
          :class="depsStatus.ollama ? 'text-green-400' : 'text-red-400'"
        >
          <CheckCircle2 v-if="depsStatus.ollama" :size="11" /><AlertTriangle
            v-else
            :size="11"
          />
          Ollama AI {{ depsStatus.ollama ? '(installed)' : '(missing)' }}
        </div>
        <div
          class="flex items-center gap-1.5 text-[11px]"
          :class="
            depsStatus.gst_plugins_bad ? 'text-green-400' : 'text-yellow-400'
          "
        >
          <CheckCircle2
            v-if="depsStatus.gst_plugins_bad"
            :size="11"
          /><AlertTriangle v-else :size="11" /> Audio Recording
          {{
            depsStatus.gst_plugins_bad
              ? '(ready)'
              : '(needs gstreamer1.0-plugins-bad)'
          }}
        </div>
        <SButton
          variant="primary"
          :disabled="setupRunning"
          :icon="Wrench"
          class="mt-1"
          @click="runSystemSetup"
        >
          <Loader v-if="setupRunning" :size="12" class="animate-spin" />
          {{ setupRunning ? 'Installing…' : 'Install Missing Dependencies' }}
        </SButton>
      </div>
      <div
        v-if="setupOutput"
        class="p-2 rounded-md bg-black/30 text-[10px] font-mono text-green-300 max-h-32 overflow-y-auto whitespace-pre-wrap"
      >
        {{ setupOutput }}
      </div>
    </div>
  </AccordionItem>

  <!-- Release notes (merged from former "What's New" tab) -->
  <SettingsSection
    title="Release Notes"
    :icon="Newspaper"
    description="What changed in this and recent versions"
    setting-key="Release notes"
    card-class="p-0"
  >
    <div
      class="changelog markdown-body px-4 py-3 max-h-[460px] overflow-y-auto text-[12px] text-text-secondary"
      v-html="renderedChangelog"
    />
  </SettingsSection>

  <!-- Danger Zone -->
  <SettingsSection
    title="Danger Zone"
    :icon="InfoIcon"
    description="Irreversible maintenance actions"
    setting-key="Reset database"
    card-class="p-0"
  >
    <div class="bg-surface p-3">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-[12px] font-medium text-danger">Reset Database</div>
          <div class="text-[11px] text-text-secondary">
            Delete all entries, tags, and media.
          </div>
        </div>
        <SButton variant="danger-soft" @click="showResetConfirm = true"
          >Reset</SButton
        >
      </div>
      <div
        v-if="showResetConfirm"
        class="mt-2.5 p-2.5 bg-danger/10 rounded-md border border-danger/40 space-y-2"
      >
        <p
          class="text-[12px] text-danger font-medium flex items-center gap-1.5"
        >
          <AlertTriangle :size="12" /> This cannot be undone.
        </p>
        <input
          v-model="resetConfirmText"
          class="w-full px-2 py-1 bg-surface border border-danger/40 rounded-md text-[12px] text-text-primary placeholder-text-muted outline-none focus:border-danger transition-colors"
          placeholder='Type "RESET" to confirm'
        />
        <div class="flex items-center gap-2">
          <SButton
            variant="danger"
            :disabled="resetConfirmText !== 'RESET' || resetting"
            @click="handleReset"
          >
            <Loader v-if="resetting" :size="11" class="animate-spin" />
            {{ resetting ? 'Erasing…' : 'Erase Everything' }}
          </SButton>
          <SButton
            variant="ghost"
            @click="showResetConfirm = false; resetConfirmText = ''"
            >Cancel</SButton
          >
        </div>
      </div>
    </div>
  </SettingsSection>
</template>

<style scoped>
.logo-mark {
  filter: brightness(0) invert(1);
}
.changelog :deep(h2) {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 1rem 0 0.4rem;
  padding-bottom: 0.2rem;
  border-bottom: 1px solid var(--color-border);
}
.changelog :deep(h2:first-child) {
  margin-top: 0;
}
.changelog :deep(h3) {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0.7rem 0 0.3rem;
}
.changelog :deep(ul) {
  margin: 0.25rem 0 0.5rem 1.1rem;
  list-style: disc;
}
.changelog :deep(li) {
  margin: 0.15rem 0;
  line-height: 1.45;
}
.changelog :deep(p) {
  margin: 0.3rem 0;
  line-height: 1.5;
}
.changelog :deep(hr) {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 0.9rem 0;
}
.changelog :deep(a) {
  color: var(--color-accent);
  text-decoration: underline;
}
.changelog :deep(code) {
  font-size: 0.82em;
  background: var(--color-surface);
  padding: 0.1em 0.3em;
  border-radius: 3px;
}
</style>
