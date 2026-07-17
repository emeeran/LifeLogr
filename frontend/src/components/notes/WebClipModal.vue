<script setup lang="ts">
import { ref, nextTick } from 'vue'

// URL prompt for the web-page clip. On desktop the page is captured as a
// picture (then OCR'd); this same URL feeds the text-extraction fallback.
const url = ref('')
const inputEl = ref<HTMLInputElement | null>(null)

const emit = defineEmits<{ clip: [url: string]; cancel: [] }>()

function submit() {
  let u = url.value.trim()
  if (!u) return
  if (!/^https?:\/\//i.test(u)) u = 'https://' + u
  emit('clip', u)
}
defineExpose({
  reset: () => {
    url.value = ''
    void nextTick(() => inputEl.value?.focus())
  },
})
</script>

<template>
  <div class="wc-mask" @click.self="emit('cancel')">
    <div class="wc-modal">
      <div class="wc-title">Clip web page</div>
      <p class="wc-sub">On desktop the page is captured as a picture and OCR'd; otherwise its text is extracted.</p>
      <input
        ref="inputEl"
        v-model="url"
        type="url"
        placeholder="https://example.com/article"
        class="wc-input"
        @keydown.enter="submit"
        @keydown.esc="emit('cancel')"
      />
      <div class="wc-actions">
        <button class="wc-btn wc-cancel" @click="emit('cancel')">Cancel</button>
        <button class="wc-btn wc-go" :disabled="!url.trim()" @click="submit">Clip</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wc-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 18vh;
  background: rgba(0, 0, 0, 0.45);
}
.wc-modal {
  width: 420px;
  max-width: calc(100vw - 2rem);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0.6rem;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.4);
  padding: 0.9rem 1rem;
}
.wc-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 0.2rem;
}
.wc-sub {
  font-size: 11px;
  color: var(--color-text-muted);
  margin: 0 0 0.6rem;
  line-height: 1.4;
}
.wc-input {
  width: 100%;
  padding: 0.4rem 0.5rem;
  background: var(--color-surface-hover);
  border: 1px solid var(--color-border);
  border-radius: 0.35rem;
  font-size: 12px;
  color: var(--color-text-primary);
  outline: none;
}
.wc-input:focus { border-color: var(--color-accent); }
.wc-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  margin-top: 0.7rem;
}
.wc-btn {
  padding: 0.3rem 0.7rem;
  border-radius: 0.35rem;
  font-size: 12px;
  cursor: pointer;
}
.wc-cancel {
  color: var(--color-text-secondary);
  background: var(--color-surface-hover);
}
.wc-cancel:hover { color: var(--color-text-primary); }
.wc-go {
  color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
}
.wc-go:disabled { opacity: 0.5; cursor: default; }
</style>
