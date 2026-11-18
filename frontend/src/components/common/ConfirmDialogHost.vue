<script setup lang="ts">
import ConfirmDialog from './ConfirmDialog.vue'
import { useConfirm } from '../../composables/useConfirm'

const { current, settle } = useConfirm()
</script>

<template>
  <ConfirmDialog
    v-if="current"
    :title="current.title"
    :message="current.message"
    :confirm-label="current.confirmLabel ?? 'Confirm'"
    :cancel-label="current.cancelLabel ?? 'Cancel'"
    @confirm="settle(true)"
    @cancel="settle(false)"
  />
</template>
