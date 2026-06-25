<script setup lang="ts">
/**
 * WhatsNewDialog — first-run "what changed" modal, shown once per version
 * upgrade. The full, browsable changelog now lives in the About settings tab;
 * this dialog is a lightweight welcome that marks the version seen.
 */
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { X, Sparkles } from 'lucide-vue-next'
import { APP_VERSION } from '../../../version'
import { useUpdateChecker } from '../../../composables/useUpdateChecker'
import changelogRaw from '../../../../../CHANGELOG.md?raw'

const modelValue = defineModel<boolean>({ default: false })
const { markCurrentVersionSeen } = useUpdateChecker()

/** Only the latest version's section. */
const latestNotes = computed(() => {
  const cutAt = changelogRaw.indexOf('\n## [')
  const body = cutAt >= 0 ? changelogRaw.slice(cutAt + 1) : changelogRaw
  const nextH2 = body.indexOf('\n## [', 1)
  const section = nextH2 >= 0 ? body.slice(0, nextH2) : body
  return DOMPurify.sanitize(marked(section) as string)
})

function close() {
  markCurrentVersionSeen()
  modelValue.value = false
}
</script>

<template>
  <Transition name="fade">
    <div v-if="modelValue" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" @click.self="close">
      <div class="bg-surface rounded-lg shadow-xl w-full max-w-lg border border-border">
        <div class="flex items-center gap-2 px-4 py-3 border-b border-border">
          <Sparkles :size="16" class="text-accent" />
          <h3 class="text-sm font-semibold text-text-primary">Welcome to LifeLogr v{{ APP_VERSION }}</h3>
          <button class="ml-auto p-1 rounded hover:bg-surface-hover text-text-muted cursor-pointer" aria-label="Close" @click="close">
            <X :size="14" />
          </button>
        </div>
        <div class="changelog markdown-body px-4 py-3 max-h-[60vh] overflow-y-auto text-[12px] text-text-secondary"
          v-html="latestNotes" />
        <div class="flex justify-end px-4 py-3 border-t border-border">
          <button class="px-3 py-1.5 rounded-md bg-accent text-white text-xs font-medium cursor-pointer hover:bg-accent-hover transition-colors" @click="close">
            Got it
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.changelog :deep(h2) { font-size: 0.95rem; font-weight: 600; color: var(--color-text-primary); margin: 0 0 0.4rem; padding-bottom: 0.2rem; border-bottom: 1px solid var(--color-border); }
.changelog :deep(h3) { font-size: 0.78rem; font-weight: 600; color: var(--color-text-primary); margin: 0.7rem 0 0.3rem; }
.changelog :deep(ul) { margin: 0.25rem 0 0.5rem 1.1rem; list-style: disc; }
.changelog :deep(li) { margin: 0.15rem 0; line-height: 1.45; }
.changelog :deep(a) { color: var(--color-accent); text-decoration: underline; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
