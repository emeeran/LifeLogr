<script setup lang="ts">
/**
 * "What's New" tab — offline-first release notes + update checker.
 *
 * The changelog is baked into the bundle at build time (`CHANGELOG.md?raw`),
 * so it is always available and always matches the installed version. The
 * update checker is the only network-dependent piece and degrades to an
 * "offline" message without disturbing the rest of the view.
 */
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  RefreshCw, CheckCircle2, DownloadCloud, WifiOff, Tag, ExternalLink,
} from 'lucide-vue-next'
import { APP_VERSION } from '../../../version'
import { useUpdateChecker } from '../../../composables/useUpdateChecker'
import SettingsSection from '../shared/SettingsSection.vue'

// Bake the changelog into the bundle — always offline-available.
import changelogRaw from '../../../../../CHANGELOG.md?raw'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

const { status, checkedAt, check } = useUpdateChecker()
const checking = computed(() => status.value.kind === 'checking')

/** Render only the changelog (strip the intro blurb above the first `## [`). */
const renderedChangelog = computed(() => {
  const cutAt = changelogRaw.indexOf('\n## [')
  const body = cutAt >= 0 ? changelogRaw.slice(cutAt + 1) : changelogRaw
  const html = marked(body) as string
  return DOMPurify.sanitize(html)
})

function fmtDate(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
    })
  } catch {
    return iso
  }
}

async function handleCheck() {
  await check()
  const s = status.value
  if (s.kind === 'available') {
    emit('toast', 'info', `LifeLogr ${s.latest} is available`)
  } else if (s.kind === 'up-to-date') {
    emit('toast', 'success', `You're on the latest version (${APP_VERSION})`)
  } else if (s.kind === 'offline') {
    emit('toast', 'error', 'Could not check for updates (offline)')
  }
}
</script>

<template>
  <!-- ── Version + Update check ────────────────────────────────────── -->
  <SettingsSection title="Version" :icon="Tag" description="Installed version and update check"
    card-class="p-4">
    <div class="flex flex-col gap-3">
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="text-[12px] text-text-secondary">Installed version</div>
          <div class="text-lg font-semibold text-text-primary">v{{ APP_VERSION }}</div>
        </div>

        <!-- Result chip (right side) -->
        <div class="flex flex-col items-end gap-1">
          <span v-if="status.kind === 'up-to-date'"
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-100 text-green-700 text-[11px] font-medium">
            <CheckCircle2 :size="12" /> Up to date
          </span>
          <span v-else-if="status.kind === 'available'"
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent/15 text-accent text-[11px] font-medium animate-pulse">
            <DownloadCloud :size="12" /> {{ status.latest }} available
          </span>
          <span v-else-if="status.kind === 'offline'"
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-100 text-amber-700 text-[11px] font-medium">
            <WifiOff :size="12" /> Offline
          </span>
          <span v-else
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface text-text-muted text-[11px] font-medium">
            <Tag :size="12" /> Not checked yet
          </span>
        </div>
      </div>

      <!-- Update-available banner -->
      <div v-if="status.kind === 'available'"
        class="rounded-md border border-accent/30 bg-accent/5 p-3 space-y-2">
        <div class="flex items-center justify-between gap-2">
          <div>
            <div class="text-[12px] font-medium text-accent flex items-center gap-1.5">
              <DownloadCloud :size="13" /> LifeLogr {{ status.latest }}
              <span v-if="status.publishedAt" class="text-[10px] text-text-muted font-normal">
                · {{ fmtDate(status.publishedAt) }}
              </span>
            </div>
          </div>
          <a :href="status.url" target="_blank" rel="noopener noreferrer"
            class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium bg-accent text-white hover:bg-accent-hover transition-colors shrink-0">
            Download <ExternalLink :size="11" />
          </a>
        </div>
        <div v-if="status.notes"
          class="text-[11px] text-text-secondary max-h-40 overflow-y-auto whitespace-pre-line pr-1
                 [&_a]:text-accent [&_a]:underline">
          {{ status.notes.replace(/#[^\n]*\n/g, '').slice(0, 600) }}{{
            status.notes.length > 600 ? '…' : '' }}
        </div>
      </div>

      <div class="flex items-center justify-between gap-2 pt-1">
        <button :disabled="checking" @click="handleCheck"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium
                 bg-white border border-border text-text-secondary hover:border-accent/50 hover:text-accent
                 disabled:opacity-50 cursor-pointer transition-colors">
          <RefreshCw :size="12" :class="{ 'animate-spin': checking }" />
          {{ checking ? 'Checking…' : 'Check for updates' }}
        </button>
        <span v-if="checkedAt" class="text-[10px] text-text-muted">
          Last checked {{ fmtDate(checkedAt.toISOString()) }}
        </span>
      </div>
    </div>
  </SettingsSection>

  <!-- ── Release notes (baked-in changelog) ────────────────────────── -->
  <SettingsSection title="Release Notes" :icon="Tag" description="What changed in this and recent versions"
    card-class="p-0">
    <div class="changelog markdown-body px-4 py-3 max-h-[460px] overflow-y-auto text-[12px] text-text-secondary"
      v-html="renderedChangelog" />
  </SettingsSection>
</template>

<style scoped>
.changelog :deep(h2) {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 1rem 0 0.4rem;
  padding-bottom: 0.2rem;
  border-bottom: 1px solid var(--color-border);
}
.changelog :deep(h2:first-child) { margin-top: 0; }
.changelog :deep(h3) {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0.7rem 0 0.3rem;
}
.changelog :deep(ul) { margin: 0.25rem 0 0.5rem 1.1rem; list-style: disc; }
.changelog :deep(li) { margin: 0.15rem 0; line-height: 1.45; }
.changelog :deep(p) { margin: 0.3rem 0; line-height: 1.5; }
.changelog :deep(hr) { border: none; border-top: 1px solid var(--color-border); margin: 0.9rem 0; }
.changelog :deep(a) { color: var(--color-accent); text-decoration: underline; }
.changelog :deep(code) {
  font-size: 0.82em;
  background: var(--color-surface);
  padding: 0.1em 0.3em;
  border-radius: 3px;
}
</style>
