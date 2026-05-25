<script setup lang="ts">
import { ref, computed } from 'vue'
import { Calendar, X } from 'lucide-vue-next'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  select: [date: string]
}>()

const now = new Date()
const selectedYear = ref(now.getFullYear())
const selectedMonth = ref(now.getMonth() + 1) // 1-based
const selectedDay = ref<number | null>(now.getDate())

const months = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
]

const years = computed(() => {
  const arr: number[] = []
  for (let y = 2000; y <= 2050; y++) arr.push(y)
  return arr
})

function close() {
  emit('update:modelValue', false)
}

function confirm() {
  const d = selectedDay.value ?? 1
  const dateStr = `${selectedYear.value}-${String(selectedMonth.value).padStart(2, '0')}-${String(d).padStart(2, '0')}`
  emit('select', dateStr)
  close()
}
</script>

<template>
  <Transition name="modal">
    <div v-if="modelValue" class="fixed inset-0 z-[300] flex items-center justify-center bg-black/40" @click.self="close">
      <div class="bg-surface border border-border rounded-xl w-[340px] shadow-2xl overflow-hidden">
        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-border">
          <div class="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <Calendar :size="16" class="text-accent" />
            Go to Date
          </div>
          <button @click="close" class="p-1 hover:bg-surface-hover rounded text-text-muted cursor-pointer">
            <X :size="14" />
          </button>
        </div>

        <!-- Year selector -->
        <div class="px-4 pt-4 pb-2">
          <label class="text-[10px] font-bold text-text-muted uppercase tracking-wider block mb-1">Year</label>
          <select
            v-model="selectedYear"
            class="w-full bg-surface-hover border border-border rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent cursor-pointer"
          >
            <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
          </select>
        </div>

        <!-- Month buttons -->
        <div class="px-4 pb-2">
          <label class="text-[10px] font-bold text-text-muted uppercase tracking-wider block mb-1">Month</label>
          <div class="grid grid-cols-4 gap-1">
            <button
              v-for="(m, i) in months"
              :key="i"
              @click="selectedMonth = i + 1"
              class="py-1.5 rounded text-xs font-medium cursor-pointer transition-colors"
              :class="selectedMonth === i + 1
                ? 'bg-accent text-white'
                : 'bg-surface-hover text-text-secondary hover:text-text-primary hover:bg-accent/10'"
            >
              {{ m }}
            </button>
          </div>
        </div>

        <!-- Optional day input -->
        <div class="px-4 pb-4">
          <label class="text-[10px] font-bold text-text-muted uppercase tracking-wider block mb-1">Day (optional)</label>
          <input
            v-model.number="selectedDay"
            type="number"
            min="1"
            max="31"
            placeholder="1"
            class="w-full bg-surface-hover border border-border rounded-lg px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
          />
        </div>

        <!-- Actions -->
        <div class="flex gap-2 px-4 pb-4">
          <button
            @click="close"
            class="flex-1 py-2 rounded-lg text-xs font-medium bg-surface-hover text-text-secondary hover:text-text-primary cursor-pointer transition-colors"
          >
            Cancel
          </button>
          <button
            @click="confirm"
            class="flex-1 py-2 rounded-lg text-xs font-medium bg-accent text-white hover:bg-accent/90 cursor-pointer transition-colors"
          >
            Go
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
