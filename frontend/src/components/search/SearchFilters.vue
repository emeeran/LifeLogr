<script setup lang="ts">
import { Calendar } from 'lucide-vue-next'

const dateFrom = defineModel<string>('dateFrom', { default: '' })
const dateTo = defineModel<string>('dateTo', { default: '' })
</script>

<template>
  <div class="flex items-center gap-2 px-4 py-2 border-b border-border">
    <div class="flex items-center gap-1.5">
      <Calendar :size="11" class="text-text-muted shrink-0" />
      <input
        :value="dateFrom"
        type="date"
        placeholder="From"
        class="bg-surface-hover border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none hover:border-accent transition-colors w-[120px]"
        @input="dateFrom = ($event.target as HTMLInputElement).value"
      />
      <span class="text-text-muted text-[10px]">-</span>
      <input
        :value="dateTo"
        type="date"
        placeholder="To"
        class="bg-surface-hover border border-border rounded px-1.5 py-0.5 text-[10px] text-text-primary outline-none hover:border-accent transition-colors w-[120px]"
        @input="dateTo = ($event.target as HTMLInputElement).value"
      />
    </div>
    <button
      v-if="dateFrom || dateTo"
      class="text-[10px] text-text-muted hover:text-text-primary cursor-pointer"
      @click="dateFrom = ''; dateTo = ''"
    >
      Clear
    </button>
  </div>
</template>
