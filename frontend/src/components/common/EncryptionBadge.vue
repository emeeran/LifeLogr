<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Lock, Unlock, Loader } from 'lucide-vue-next'
import { errorMessage } from '../../utils/errorMessage'
import { useToastStore } from '../../stores/toast'

/**
 * Lock toggle + inline passphrase prompt shared by entries and notes.
 * The caller owns the API surface (check/encrypt/decrypt) and the wording
 * (entity label + what encryption covers); this owns the UI and error flow.
 */
const toast = useToastStore()

const props = defineProps<{
  isEncrypted: boolean
  /** Noun for tooltips: "entry" or "note". */
  entityLabel: string
  /** Help sentence under the encrypt prompt (what stays unencrypted). */
  scopeNote: string
  checkStatus: () => Promise<{ is_encrypted: boolean }>
  /** Return values are ignored — callers pass the API's typed responses. */
  encrypt: (passphrase: string) => Promise<unknown>
  decrypt: (passphrase: string) => Promise<unknown>
}>()
const emit = defineEmits<{ change: [encrypted: boolean] }>()

const loading = ref(false)
const showPrompt = ref(false)
const passphrase = ref('')
const mode = ref<'encrypt' | 'decrypt'>('encrypt')

// Sync encryption state from server on mount
onMounted(async () => {
  try {
    const status = await props.checkStatus()
    if (status.is_encrypted !== props.isEncrypted) {
      emit('change', status.is_encrypted)
    }
  } catch {
    /* ignore if endpoint unavailable */
  }
})

function startEncrypt() {
  mode.value = 'encrypt'
  passphrase.value = ''
  showPrompt.value = true
}

function startDecrypt() {
  mode.value = 'decrypt'
  passphrase.value = ''
  showPrompt.value = true
}

async function submit() {
  if (!passphrase.value) return
  loading.value = true
  try {
    if (mode.value === 'encrypt') {
      await props.encrypt(passphrase.value)
      emit('change', true)
    } else {
      await props.decrypt(passphrase.value)
      emit('change', false)
    }
    showPrompt.value = false
  } catch (e: unknown) {
    // Passphrase failures are the common case; the inline prompt stays open so
    // the user can retry, and the reason lands in the toast host.
    toast.error(
      `${mode.value === 'decrypt' ? 'Decryption' : 'Encryption'} failed: ${errorMessage(e)}`,
    )
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="relative">
    <button
      @click="isEncrypted ? startDecrypt() : startEncrypt()"
      class="p-1.5 rounded hover:bg-surface-hover transition-colors"
      :class="isEncrypted ? 'text-accent' : 'text-text-secondary'"
      :title="isEncrypted ? `Decrypt ${entityLabel}` : `Encrypt ${entityLabel}`"
    >
      <Lock v-if="isEncrypted" :size="16" />
      <Unlock v-else :size="16" />
    </button>

    <!-- Passphrase modal -->
    <div
      v-if="showPrompt"
      class="absolute right-0 top-8 bg-surface border border-border rounded-lg p-4 w-64 shadow-xl z-50 space-y-3"
    >
      <div class="text-sm font-medium text-text-primary">
        {{
          mode === 'encrypt'
            ? 'Set encryption passphrase'
            : 'Enter passphrase to decrypt'
        }}
      </div>
      <p
        v-if="mode === 'encrypt'"
        class="text-[10px] leading-snug text-text-muted"
      >
        {{ scopeNote }}
      </p>
      <input
        v-model="passphrase"
        type="password"
        placeholder="Passphrase"
        class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary"
        @keydown.enter="submit"
      />
      <div class="flex gap-2 justify-end">
        <button
          @click="showPrompt = false"
          class="px-3 py-1 text-sm bg-surface-hover text-text-secondary rounded hover:bg-border"
        >
          Cancel
        </button>
        <button
          @click="submit"
          :disabled="loading || !passphrase"
          class="px-3 py-1 text-sm bg-accent text-white rounded hover:bg-accent/90 disabled:opacity-50 flex items-center gap-1"
        >
          <Loader v-if="loading" :size="12" class="animate-spin" />
          {{ mode === 'encrypt' ? 'Encrypt' : 'Decrypt' }}
        </button>
      </div>
    </div>
  </div>
</template>
