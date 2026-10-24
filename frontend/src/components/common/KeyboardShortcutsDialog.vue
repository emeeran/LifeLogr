<script setup lang="ts">
import { useModalFocus } from '../../composables/useModalFocus'
import { SHORTCUT_GROUPS } from '../../composables/shortcutRegistry'

const emit = defineEmits<{ close: [] }>()

// Modal a11y: role="dialog", focus trap, Esc + focus restore.
const modal = useModalFocus(
  () => true,
  () => emit('close'),
)
</script>

<template>
  <div
    class="fixed inset-0 z-[300] flex items-start justify-center pt-[12vh] bg-black/40"
    @click.self="emit('close')"
  >
    <div
      ref="modal.container"
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      tabindex="-1"
      class="bg-surface border border-border rounded-xl w-[520px] max-h-[70vh] flex flex-col shadow-2xl overflow-hidden"
      @keydown="modal.onKeydown"
    >
      <!-- Header -->
      <div class="flex items-center gap-2 px-4 py-3 border-b border-border">
        <h2 class="text-sm font-semibold text-text-primary flex-1">
          Keyboard shortcuts
        </h2>
        <kbd
          class="text-[10px] text-text-muted bg-surface-hover border border-border rounded px-1.5 py-0.5"
          >Esc</kbd
        >
      </div>

      <!-- Groups -->
      <div class="overflow-y-auto custom-scrollbar p-4 space-y-4">
        <section v-for="group in SHORTCUT_GROUPS" :key="group.title">
          <h3
            class="text-[9px] font-bold text-text-muted uppercase tracking-wider mb-1.5"
          >
            {{ group.title }}
          </h3>
          <ul class="space-y-0.5">
            <li
              v-for="item in group.items"
              :key="item.label"
              class="flex items-center justify-between gap-3 px-2 py-1 rounded hover:bg-surface-hover text-[11px]"
            >
              <span class="text-text-secondary">{{ item.label }}</span>
              <span class="flex items-center gap-1 shrink-0">
                <kbd
                  v-for="(key, i) in item.keys"
                  :key="i"
                  class="text-[10px] text-text-secondary bg-surface-hover border border-border rounded px-1.5 py-0.5"
                  >{{ key }}</kbd
                >
              </span>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>
