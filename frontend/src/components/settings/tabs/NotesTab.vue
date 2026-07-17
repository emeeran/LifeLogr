<script setup lang="ts">
/**
 * NotesTab — preferences for the Notes module.
 *
 * The note editor's "Read" button now uses the global Edge TTS voice (the same
 * one used by the journal editor and the email speaker). That voice is set once,
 * app-wide, under Settings → Features → Read Aloud — so this tab no longer holds
 * its own (conflicting) system-voice picker.
 */
import { Volume2 } from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
</script>

<template>
  <SettingsSection
    title="Read aloud"
    :icon="Volume2"
    description="Voice used by the Read button in the note editor."
  >
    <p class="px-1 text-xs leading-relaxed text-text-secondary">
      The note editor shares one read-aloud voice with the journal editor and the
      email speaker. Set it under
      <span class="font-medium text-text-primary">Settings → Features → Read Aloud</span>
      — the same voice, speed and volume apply everywhere.
    </p>
  </SettingsSection>
</template>
