<script setup lang="ts">
import { onMounted } from 'vue'
import { useRemindersStore } from '../../stores/reminders'
import { Bell, Plus, Trash2, Play, Clock } from 'lucide-vue-next'
import { ref } from 'vue'

const store = useRemindersStore()
const showForm = ref(false)
const form = ref({ title: '', message: '', reminder_time: '21:00', days_of_week: '1,2,3,4,5' })

onMounted(() => store.fetchAll())

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function dayLabels(daysStr: string): string {
  const active = daysStr.split(',').map(Number)
  return DAYS.map((d, i) => active.includes(i) ? d : '').filter(Boolean).join(' ')
}

async function createReminder() {
  if (!form.value.title) return
  await store.create(form.value)
  showForm.value = false
  form.value = { title: '', message: '', reminder_time: '21:00', days_of_week: '1,2,3,4,5' }
}

async function toggleActive(id: number, current: boolean) {
  await store.update(id, { is_active: !current })
}

async function testReminder(id: number) {
  const result = await store.testNotification(id)
  alert(result.sent ? `Notification sent: "${result.title}"` : 'Failed to send')
}
</script>

<template>
  <div class="h-full overflow-y-auto p-6 space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-text-primary flex items-center gap-2"><Bell :size="24" /> Reminders</h1>
      <button @click="showForm = !showForm"
        class="px-3 py-1.5 bg-accent text-white text-sm rounded hover:bg-accent/90 flex items-center gap-1">
        <Plus :size="16" /> New Reminder
      </button>
    </div>

    <!-- Create Form -->
    <div v-if="showForm" class="bg-surface rounded-lg p-4 border border-border space-y-3">
      <input v-model="form.title" placeholder="Title (e.g., Evening journal)"
        class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
      <input v-model="form.message" placeholder="Message (optional)"
        class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
      <div class="flex gap-4 items-center">
        <div>
          <label class="text-xs text-text-secondary">Time</label>
          <input v-model="form.reminder_time" type="time"
            class="block px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
        </div>
        <div>
          <label class="text-xs text-text-secondary">Days (0=Mon..6=Sun, comma-separated)</label>
          <input v-model="form.days_of_week"
            class="block px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
        </div>
      </div>
      <div class="flex gap-2">
        <button @click="createReminder" class="px-4 py-1.5 bg-accent text-white text-sm rounded hover:bg-accent/90">Create</button>
        <button @click="showForm = false" class="px-4 py-1.5 bg-surface-hover text-text-secondary text-sm rounded hover:bg-border">Cancel</button>
      </div>
    </div>

    <!-- Reminder List -->
    <div v-if="store.loading" class="text-text-secondary text-sm">Loading...</div>
    <div v-else-if="store.reminders.length === 0" class="text-text-secondary text-sm py-8 text-center">
      No reminders set. Create one to get daily journaling prompts.
    </div>
    <div v-else class="space-y-3">
      <div v-for="r in store.reminders" :key="r.id"
        class="bg-surface rounded-lg p-4 border border-border"
        :class="{ 'opacity-50': !r.is_active }">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm font-medium text-text-primary">{{ r.title }}</div>
            <div v-if="r.message" class="text-xs text-text-secondary mt-0.5">{{ r.message }}</div>
            <div class="flex items-center gap-3 mt-1 text-xs text-text-secondary">
              <span class="flex items-center gap-1"><Clock :size="12" /> {{ r.reminder_time }}</span>
              <span>{{ dayLabels(r.days_of_week) }}</span>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button @click="testReminder(r.id)" class="p-1.5 rounded hover:bg-surface-hover text-text-secondary" title="Test notification">
              <Play :size="14" />
            </button>
            <button @click="toggleActive(r.id, r.is_active)"
              class="px-2 py-1 text-xs rounded" :class="r.is_active ? 'bg-accent/10 text-accent' : 'bg-surface-hover text-text-secondary'">
              {{ r.is_active ? 'Active' : 'Paused' }}
            </button>
            <button @click="store.remove(r.id)" class="p-1.5 rounded hover:bg-red-500/10 text-red-400" title="Delete">
              <Trash2 :size="14" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
