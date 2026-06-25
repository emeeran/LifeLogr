<script setup lang="ts">
/**
 * WhatsNewDialog — first-run "What's New" modal.
 *
 * Shown once when the installed version is newer than the version the user last
 * acknowledged (e.g. after an upgrade or a fresh install). It parses the baked-in
 * CHANGELOG.md and surfaces only the entries newer than the last-seen version,
 * so returning users see exactly what changed since their previous build — not
 * the entire history. Fully offline (the changelog ships in the bundle).
 */
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { Sparkles, ExternalLink } from 'lucide-vue-next'
import BaseModal from '../../common/BaseModal.vue'
import { APP_VERSION } from '../../../version'
import { useUpdateChecker, REPO_URL } from '../../../composables/useUpdateChecker'

import changelogRaw from '../../../../../CHANGELOG.md?raw'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const { lastSeenVersion, markCurrentVersionSeen } = useUpdateChecker()

const previousVersion = computed(() => lastSeenVersion.value || null)

interface ReleaseSection { version: string; html: string }

/** Split the changelog into per-version sections (one `## [x.y.z]` each). */
function splitChangelog(): ReleaseSection[] {
  const cutAt = changelogRaw.indexOf('\n## [')
  const body = cutAt >= 0 ? changelogRaw.slice(cutAt + 1) : changelogRaw
  const sections: ReleaseSection[] = []
  // `## [0.2.1] — date` ... up to the next `## [` (or EOF).
  const re = /^## \[([^\]]+)\][^\n]*\n([\s\S]*?)(?=^## \[|\Z)/gm
  let m: RegExpExecArray | null
  while ((m = re.exec(body)) !== null) {
    const version = m[1].trim()
    const html = DOMPurify.sanitize(marked(m[2].trim()) as string)
    sections.push({ version, html })
  }
  return sections
}

/** True if `ver` is strictly newer than `prev` (semver); always true if no prev. */
function isNewerThan(prev: string | null, ver: string): boolean {
  if (!prev) return true
  const pa = prev.replace(/^v/i, '').match(/^(\d+)\.(\d+)\.(\d+)/)
  const pb = ver.replace(/^v/i, '').match(/^(\d+)\.(\d+)\.(\d+)/)
  if (!pa || !pb) return ver !== prev
  for (let i = 1; i <= 3; i++) {
    const a = Number(pa[i]), b = Number(pb[i])
    if (b !== a) return b > a
  }
  return false
}

/** Only the changelog entries newer than the user's last-seen version. */
const newSections = computed<ReleaseSection[]>(() => {
  const prev = previousVersion.value
  return splitChangelog().filter(s => isNewerThan(prev, s.version))
})

/** Is this a fresh install (no previous version recorded)? */
const isFreshInstall = computed(() => !previousVersion.value)

function dismiss() {
  markCurrentVersionSeen()
  emit('update:modelValue', false)
}
</script>

<template>
  <BaseModal :model-value="props.modelValue" @update:model-value="emit('update:modelValue', $event)"
    :icon="Sparkles" :title="isFreshInstall ? `Welcome to LifeLogr v${APP_VERSION}` : `What's New in v${APP_VERSION}`"
    max-width="560px">
    <div class="space-y-4">
      <!-- Fresh install: friendly intro -->
      <p v-if="isFreshInstall" class="text-[12px] text-text-secondary leading-relaxed">
        Welcome aboard! Here's what's included in this build. You can revisit these
        notes anytime under <strong>Settings → What's New</strong>.
      </p>
      <!-- Upgrade: contextual -->
      <p v-else class="text-[12px] text-text-secondary leading-relaxed">
        You've upgraded from <strong>v{{ previousVersion }}</strong>. Here's what's
        new since your last version.
      </p>

      <!-- No new sections (edge case: dev build with same changelog) -->
      <div v-if="!newSections.length" class="rounded-md border border-border bg-white/60 p-3 text-[12px] text-text-muted">
        No specific release notes to highlight — enjoy the latest build.
      </div>

      <!-- Rendered per-version sections -->
      <div v-for="s in newSections" :key="s.version"
        class="changelog rounded-md border border-border bg-white/60 p-3"
        v-html="s.html" />
    </div>

    <template #footer>
      <a :href="REPO_URL" target="_blank" rel="noopener noreferrer"
        class="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-[12px] text-text-secondary hover:text-accent transition-colors mr-auto">
        <ExternalLink :size="12" /> View on GitHub
      </a>
      <button @click="dismiss"
        class="px-3 py-1.5 rounded-md text-[12px] font-medium bg-accent text-white hover:bg-accent-hover transition-colors cursor-pointer">
        {{ isFreshInstall ? 'Get started' : 'Got it' }}
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
.changelog :deep(h3) {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0.6rem 0 0.25rem;
}
.changelog :deep(h3:first-child) { margin-top: 0; }
.changelog :deep(ul) { margin: 0.2rem 0 0.4rem 1.1rem; list-style: disc; }
.changelog :deep(li) { margin: 0.12rem 0; line-height: 1.45; font-size: 0.78rem; color: var(--color-text-secondary); }
.changelog :deep(p) { margin: 0.25rem 0; font-size: 0.78rem; }
.changelog :deep(a) { color: var(--color-accent); text-decoration: underline; }
.changelog :deep(code) {
  font-size: 0.82em;
  background: var(--color-surface);
  padding: 0.1em 0.3em;
  border-radius: 3px;
}
</style>
