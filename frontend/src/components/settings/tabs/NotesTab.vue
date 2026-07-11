<script setup lang="ts">
/**
 * NotesTab — preferences for the Notes module.
 *
 * Currently houses the read-aloud voice used by the editor's "Read" button.
 * The choice is stored in localStorage (key `lifelogr-tts-voice`) and read by
 * NoteEditor.toggleSpeak, so it applies app-wide and persists until changed.
 */
import { onMounted, ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { Volume2, Play } from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import SButton from '../shared/SButton.vue'

defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

const selectedVoiceURI = useLocalStorage<string>('lifelogr-tts-voice', '')
const voices = ref<SpeechSynthesisVoice[]>([])

function loadVoices() {
  if (typeof window === 'undefined' || !window.speechSynthesis) return
  voices.value = window.speechSynthesis.getVoices()
}

onMounted(() => {
  loadVoices()
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = loadVoices
  }
})

function testVoice() {
  const synth = typeof window !== 'undefined' ? window.speechSynthesis : null
  if (!synth) return
  synth.cancel()
  const u = new SpeechSynthesisUtterance('This is how your notes will sound when read aloud.')
  const v = voices.value.find((vv) => vv.voiceURI === selectedVoiceURI.value)
  if (v) u.voice = v
  synth.speak(u)
}
</script>

<template>
  <SettingsSection
    title="Read aloud"
    :icon="Volume2"
    description="Voice used by the Read button in the note editor."
  >
    <div class="space-y-1">
      <SettingRow label="Voice" description="Pick a system text-to-speech voice.">
        <select
          v-model="selectedVoiceURI"
          class="w-64 max-w-full rounded border border-border bg-surface-hover px-2 py-1 text-xs text-text-primary outline-none focus:border-accent"
        >
          <option value="">System default</option>
          <option v-for="v in voices" :key="v.voiceURI" :value="v.voiceURI">
            {{ v.name }} ({{ v.lang }})
          </option>
        </select>
      </SettingRow>

      <SettingRow indent label="Preview">
        <SButton :icon="Play" variant="outline" @click="testVoice">Test voice</SButton>
      </SettingRow>

      <p v-if="!voices.length" class="pl-[31px] pt-1 text-[10.5px] text-text-muted">
        No system voices detected — the default voice will be used.
      </p>
    </div>
  </SettingsSection>
</template>
