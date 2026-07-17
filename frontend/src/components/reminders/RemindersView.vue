<script setup lang="ts">
/**
 * RemindersView — schedule journaling nudges.
 *
 * UX enhancements over the original:
 *  • Friendly day chips (DayPicker) instead of raw comma-separated input.
 *  • Quick presets (Weekdays / Weekends / Every day) for one-tap setup.
 *  • Inline edit of any reminder (no separate screen), with optimistic toggle.
 *  • "Next fires" calculation so users see *when* a reminder will next ring.
 *  • Proper toast feedback for create / test / delete (no more native alert()).
 *  • Rich empty state and per-reminder last-fired timestamp.
 *  • Consistent with the app's settings styling (rounded cards, accent CTAs).
 */
import { computed, onMounted, ref } from 'vue'
import { useRemindersStore } from '../../stores/reminders'
import type { ReminderResponse } from '../../types'
import {
  Bell, BellRing, Plus, Trash2, Play, Clock, Pencil, X, Check, CalendarDays,
  Sparkles, AlertCircle, CheckCircle2,
} from 'lucide-vue-next'
import DayPicker from './DayPicker.vue'

const store = useRemindersStore()

// ── Form state ──
const showForm = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const emptyForm = () => ({ title: '', message: '', reminder_time: '21:00', days_of_week: '1,2,3,4,5' })
const form = ref(emptyForm())

// ── Toast (self-contained; view isn't inside the settings shell) ──
const toast = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error' | 'info', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3200)
}

onMounted(() => store.fetchAll())

// ── Quick presets ──
const PRESETS = [
  { label: 'Every day', days: '0,1,2,3,4,5,6' },
  { label: 'Weekdays', days: '0,1,2,3,4' },
  { label: 'Weekends', days: '5,6' },
]
function applyPreset(days: string) { form.value.days_of_week = days }

// ── Stats for the header ──
const stats = computed(() => ({
  total: store.reminders.length,
  active: store.reminders.filter(r => r.is_active).length,
}))

const sortedReminders = computed(() =>
  [...store.reminders].sort((a, b) => a.reminder_time.localeCompare(b.reminder_time)),
)

// ── "Next fires" helper ──
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
function activeDayIndices(daysStr: string): number[] {
  return daysStr.split(',').map(s => parseInt(s.trim(), 10)).filter(n => n >= 0 && n <= 6)
}
function nextFiresAt(r: ReminderResponse): string {
  if (!r.is_active) return 'Paused'
  const days = activeDayIndices(r.days_of_week)
  if (!days.length) return 'No days selected'
  const [h, m] = r.reminder_time.split(':').map(Number)
  const now = new Date()
  for (let i = 0; i <= 7; i++) {
    const d = new Date(now)
    d.setDate(now.getDate() + i)
    // JS getDay(): Sun=0..Sat=6. Our convention: Mon=0..Sun=6.
    const ourIdx = (d.getDay() + 6) % 7
    if (!days.includes(ourIdx)) continue
    d.setHours(h, m, 0, 0)
    if (d.getTime() > now.getTime()) {
      const isToday = i === 0
      const isTomorrow = i === 1
      const label = isToday ? 'Today' : isTomorrow ? 'Tomorrow' : DAY_NAMES[ourIdx]
      const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
      return `${label} ${time}`
    }
  }
  return '—'
}

function relativeLastFired(iso: string | null): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  const diff = Date.now() - then
  const mins = Math.round(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.round(hrs / 24)
  return `${days}d ago`
}

// ── CRUD actions ──
function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  showForm.value = true
}
function openEdit(r: ReminderResponse) {
  editingId.value = r.id
  form.value = { title: r.title, message: r.message ?? '', reminder_time: r.reminder_time.slice(0, 5), days_of_week: r.days_of_week }
  showForm.value = true
}
function cancelForm() {
  showForm.value = false
  editingId.value = null
}
async function submitForm() {
  if (!form.value.title.trim()) { showToast('error', 'Title is required'); return }
  submitting.value = true
  try {
    if (editingId.value !== null) {
      await store.update(editingId.value, form.value)
      showToast('success', 'Reminder updated')
    } else {
      await store.create(form.value)
      showToast('success', 'Reminder created')
    }
    cancelForm()
  } catch {
    showToast('error', 'Could not save reminder')
  } finally {
    submitting.value = false
  }
}
async function toggleActive(r: ReminderResponse) {
  try {
    await store.update(r.id, { is_active: !r.is_active })
  } catch {
    showToast('error', 'Could not toggle reminder')
  }
}
async function testReminder(r: ReminderResponse) {
  try {
    const result = await store.testNotification(r.id)
    showToast(result.sent ? 'success' : 'error', result.sent ? `Test sent: "${r.title}"` : 'Notification failed')
  } catch {
    showToast('error', 'Could not send test')
  }
}
async function removeReminder(r: ReminderResponse) {
  if (!confirm(`Delete "${r.title}"?`)) return
  try {
    await store.remove(r.id)
    showToast('info', 'Reminder deleted')
  } catch {
    showToast('error', 'Could not delete reminder')
  }
}
</script>

<template>
  <div class="relative h-full overflow-y-auto px-6 py-5 space-y-5">
    <!-- Header -->
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
          <BellRing :size="20" class="text-accent" />
        </div>
        <div>
          <h1 class="text-xl font-bold text-text-primary leading-tight">Reminders</h1>
          <p class="text-[11px] text-text-muted mt-0.5">
            <span class="font-medium text-accent">{{ stats.active }}</span>
            <span class="text-text-secondary"> active</span>
            <span v-if="stats.total"> · {{ stats.total }} total</span>
          </p>
        </div>
      </div>
      <button @click="openCreate"
        class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover transition-colors cursor-pointer shadow-sm">
        <Plus :size="14" /> New Reminder
      </button>
    </div>

    <!-- Create / Edit form -->
    <Transition name="form-slide">
      <div v-if="showForm" class="bg-surface rounded-lg p-4 border border-accent/30 shadow-sm space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-accent flex items-center gap-1.5">
            <Sparkles :size="11" /> {{ editingId !== null ? 'Edit reminder' : 'New reminder' }}
          </span>
          <button @click="cancelForm" class="p-1 rounded hover:bg-surface-hover text-text-muted cursor-pointer"><X :size="13" /></button>
        </div>

        <input v-model="form.title" placeholder="What to remember? (e.g. Evening journal)"
          class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />

        <input v-model="form.message" placeholder="Personal message (optional)"
          class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />

        <div class="flex flex-col sm:flex-row sm:items-end gap-3">
          <div>
            <label class="block text-[10px] uppercase tracking-wide text-text-muted mb-1">Time</label>
            <input v-model="form.reminder_time" type="time"
              class="px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />
          </div>
          <div class="flex-1">
            <label class="block text-[10px] uppercase tracking-wide text-text-muted mb-1">Repeat on</label>
            <DayPicker v-model="form.days_of_week" />
          </div>
        </div>

        <!-- Presets -->
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="text-[10px] text-text-muted mr-1">Quick:</span>
          <button v-for="p in PRESETS" :key="p.label" type="button" @click="applyPreset(p.days)"
            class="px-2 py-0.5 rounded-full text-[10px] bg-surface-hover text-text-secondary hover:bg-accent/15 hover:text-accent border border-border transition-colors cursor-pointer">
            {{ p.label }}
          </button>
        </div>

        <div class="flex gap-2 pt-1">
          <button @click="submitForm" :disabled="submitting"
            class="inline-flex items-center gap-1.5 px-4 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover disabled:opacity-50 transition-colors cursor-pointer">
            <Check :size="13" /> {{ editingId !== null ? 'Save changes' : 'Create' }}
          </button>
          <button @click="cancelForm"
            class="px-3 py-1.5 bg-surface-hover text-text-secondary text-[12px] rounded-md hover:bg-border transition-colors cursor-pointer">
            Cancel
          </button>
        </div>
      </div>
    </Transition>

    <!-- Loading -->
    <div v-if="store.loading" class="text-center py-10 text-text-muted text-[13px]">Loading reminders…</div>

    <!-- Empty state -->
    <div v-else-if="store.reminders.length === 0"
      class="text-center py-12 px-6 rounded-lg border border-dashed border-border bg-surface/50">
      <div class="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mx-auto mb-3">
        <Bell :size="24" class="text-accent/70" />
      </div>
      <h3 class="text-[14px] font-medium text-text-primary">No reminders yet</h3>
      <p class="text-[12px] text-text-secondary mt-1 max-w-sm mx-auto leading-relaxed">
        Set a daily nudge to build your journaling habit. Reminders fire on the
        days and time you choose, even if the app was offline.
      </p>
      <button @click="openCreate"
        class="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover transition-colors cursor-pointer">
        <Plus :size="14" /> Create your first reminder
      </button>
    </div>

    <!-- Reminder list -->
    <div v-else class="space-y-2.5">
      <div v-for="r in sortedReminders" :key="r.id"
        class="group bg-surface rounded-lg p-3.5 border transition-all"
        :class="r.is_active ? 'border-border hover:border-accent/40' : 'border-border opacity-60'">

        <div class="flex items-start justify-between gap-3">
          <!-- Left: content -->
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-[13px] font-medium text-text-primary truncate">{{ r.title }}</span>
              <span v-if="!r.is_active"
                class="px-1.5 py-0.5 rounded-full text-[9px] uppercase tracking-wide bg-surface-hover text-text-muted">
                Paused
              </span>
              <span v-else-if="nextFiresAt(r) !== '—'"
                class="px-1.5 py-0.5 rounded-full text-[9px] uppercase tracking-wide bg-accent/10 text-accent flex items-center gap-1">
                <Clock :size="8" /> Next: {{ nextFiresAt(r) }}
              </span>
            </div>
            <p v-if="r.message" class="text-[11.5px] text-text-secondary mt-0.5 truncate">{{ r.message }}</p>
            <div class="flex items-center gap-2.5 mt-1.5 text-[11px] text-text-muted">
              <span class="flex items-center gap-1 font-medium text-text-secondary">
                <Clock :size="11" /> {{ r.reminder_time.slice(0, 5) }}
              </span>
              <span class="text-border">·</span>
              <DayPicker :model-value="r.days_of_week" disabled />
              <template v-if="relativeLastFired(r.last_fired_at)">
                <span class="text-border">·</span>
                <span class="italic">Last fired {{ relativeLastFired(r.last_fired_at) }}</span>
              </template>
            </div>
          </div>

          <!-- Right: actions -->
          <div class="flex items-center gap-1 shrink-0">
            <!-- Active toggle (custom switch) -->
            <button type="button" role="switch" :aria-checked="r.is_active" :title="r.is_active ? 'Pause' : 'Resume'"
              @click="toggleActive(r)"
              class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200"
              :class="r.is_active ? 'bg-accent' : 'bg-border'">
              <span aria-hidden="true"
                class="pointer-events-none absolute top-[2px] left-[2px] inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200"
                :class="r.is_active ? 'translate-x-4' : 'translate-x-0'" />
            </button>
            <button @click="testReminder(r)" title="Send test notification"
              class="p-1.5 rounded hover:bg-accent/10 text-text-muted hover:text-accent transition-colors cursor-pointer">
              <Play :size="13" />
            </button>
            <button @click="openEdit(r)" title="Edit"
              class="p-1.5 rounded hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors cursor-pointer">
              <Pencil :size="13" />
            </button>
            <button @click="removeReminder(r)" title="Delete"
              class="p-1.5 rounded hover:bg-danger/10 text-text-muted hover:text-danger transition-colors cursor-pointer">
              <Trash2 :size="13" />
            </button>
          </div>
        </div>
      </div>

      <!-- Helpful footer note -->
      <p class="text-[10.5px] text-text-muted text-center pt-2 flex items-center justify-center gap-1.5">
        <CalendarDays :size="11" />
        Reminders use your system clock and catch up after offline periods.
      </p>
    </div>

    <!-- Toast -->
    <Transition name="toast">
      <div v-if="toast"
        class="fixed bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 px-3.5 py-2 rounded-lg border text-[12px] shadow-lg z-50"
        :class="{
          'bg-green-900/90 border-green-700 text-green-100': toast.type === 'success',
          'bg-red-900/90 border-red-700 text-red-100': toast.type === 'error',
          'bg-surface border-border text-text-primary': toast.type === 'info',
        }">
        <CheckCircle2 v-if="toast.type === 'success'" :size="14" />
        <AlertCircle v-else-if="toast.type === 'error'" :size="14" />
        <Bell v-else :size="14" />
        {{ toast.message }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.form-slide-enter-active, .form-slide-leave-active { transition: all 0.25s ease; }
.form-slide-enter-from, .form-slide-leave-to { opacity: 0; transform: translateY(-8px); }

.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 10px); }
</style>
