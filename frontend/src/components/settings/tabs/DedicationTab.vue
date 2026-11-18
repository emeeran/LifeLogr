<script setup lang="ts">
/**
 * DedicationTab — full-bleed host for the memorial tribute.
 *
 * Renders edge-to-edge (no padding) so the tribute image fills the whole
 * panel; the settings chrome supplies the surrounding frame.
 */
import MemorialTribute from '../MemorialTribute.vue'
import memorialImg from '../../../assets/tariq-memorial-tribute.jpg'
</script>

<template>
  <div class="dedication-tab h-full w-full">
    <MemorialTribute :image="memorialImg" />
  </div>
</template>
