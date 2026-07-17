<script setup lang="ts">
/** SchedulePanel — week agenda (recurring events expanded) + inline event form. */
import { computed, onMounted, ref } from 'vue'
import { usePlannerStore } from '../../stores/planner'
import RecurrencePicker from './RecurrencePicker.vue'
import { Plus, ChevronLeft, ChevronRight, MapPin, Repeat, Clock, X, Check, AlertCircle, CheckCircle2 } from 'lucide-vue-next'

const store = usePlannerStore()

// Week navigation
const weekStart = ref(startOfWeek(new Date()))
function startOfWeek(d: Date): Date {
  const x = new Date(d)
  const day = (x.getDay() + 6) % 7 // Mon=0..Sun=6
  x.setDate(x.getDate() - day)
  x.setHours(0, 0, 0, 0)
  return x
}
function shiftWeek(days: number) {
  const x = new Date(weekStart.value)
  x.setDate(x.getDate() + days)
  weekStart.value = x
  loadAgenda()
}
const weekEnd = computed(() => {
  const x = new Date(weekStart.value)
  x.setDate(x.getDate() + 7)
  return x
})
const weekLabel = computed(() => {
  const f = weekStart.value.toLocaleDateString([], { month: 'short', day: 'numeric' })
  const t = new Date(weekEnd.value.getTime() - 86400000).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
  return `${f} – ${t}`
})

async function loadAgenda() {
  await store.fetchAgenda(weekStart.value, weekEnd.value)
}
onMounted(loadAgenda)

// Group agenda items by day
const days = computed(() => {
  const out: { date: Date; label: string; items: typeof store.agenda }[] = []
  for (let i = 0; i < 7; i++) {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    const iso = d.toISOString().slice(0, 10)
    out.push({
      date: d,
      label: d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' }),
      items: store.agenda.filter(it => it.start_at.slice(0, 10) === iso),
    })
  }
  return out
})

// Event form
const showForm = ref(false)
const submitting = ref(false)
const emptyForm = () => ({
  title: '',
  start_at: '',
  end_at: '',
  all_day: false,
  location: '',
  rrule: null as string | null,
})
const form = ref(emptyForm())
function openCreate() {
  const today = new Date()
  const base = today.toISOString().slice(0, 10)
  form.value = { ...emptyForm(), start_at: `${base}T09:00`, end_at: `${base}T10:00` }
  showForm.value = true
}
function cancelForm() { showForm.value = false }

const toast = ref<{ type: 'success' | 'error'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}

async function submitForm() {
  if (!form.value.title.trim()) { showToast('error', 'Title is required'); return }
  if (!form.value.start_at || !form.value.end_at) { showToast('error', 'Start and end are required'); return }
  submitting.value = true
  try {
    await store.createEvent({
      title: form.value.title,
      start_at: form.value.start_at,
      end_at: form.value.end_at,
      all_day: form.value.all_day,
      location: form.value.location || null,
      rrule: form.value.rrule,
    })
    showToast('success', 'Event added')
    cancelForm()
  } catch {
    showToast('error', 'Could not add event')
  } finally {
    submitting.value = false
  }
}

function fmtTime(iso: string, allDay: boolean): string {
  if (allDay) return 'All day'
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}
</script>

<template>
  <div class="h-full overflow-y-auto p-5 space-y-4">
    <!-- Header row -->
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <button @click="shiftWeek(-7)" class="p-1.5 rounded hover:bg-surface-hover text-text-secondary cursor-pointer"><ChevronLeft :size="16" /></button>
        <span class="text-[13px] font-medium text-text-primary min-w-[150px] text-center">{{ weekLabel }}</span>
        <button @click="shiftWeek(7)" class="p-1.5 rounded hover:bg-surface-hover text-text-secondary cursor-pointer"><ChevronRight :size="16" /></button>
        <button @click="weekStart = startOfWeek(new Date()); loadAgenda()" class="ml-1 text-[11px] text-accent hover:text-accent-hover">Today</button>
      </div>
      <button @click="openCreate"
        class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover transition-colors cursor-pointer shadow-sm">
        <Plus :size="14" /> New event
      </button>
    </div>

    <!-- Event form -->
    <Transition name="form-slide">
      <div v-if="showForm" class="bg-surface rounded-lg p-4 border border-accent/30 shadow-sm space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-accent">New event</span>
          <button @click="cancelForm" class="p-1 rounded hover:bg-surface-hover text-text-muted cursor-pointer"><X :size="13" /></button>
        </div>
        <input v-model="form.title" placeholder="Event title"
          class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent" />
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label class="block text-[10px] uppercase tracking-wide text-text-muted mb-1">Starts</label>
            <input v-model="form.start_at" type="datetime-local"
              class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent" />
          </div>
          <div>
            <label class="block text-[10px] uppercase tracking-wide text-text-muted mb-1">Ends</label>
            <input v-model="form.end_at" type="datetime-local"
              class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent" />
          </div>
        </div>
        <input v-model="form.location" placeholder="Location (optional)"
          class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent" />
        <RecurrencePicker v-model="form.rrule" />
        <label class="inline-flex items-center gap-2 text-[12px] text-text-secondary cursor-pointer select-none">
          <input type="checkbox" v-model="form.all_day" class="accent-[var(--color-accent)]" /> All-day event
        </label>
        <div class="flex gap-2 pt-1">
          <button @click="submitForm" :disabled="submitting"
            class="inline-flex items-center gap-1.5 px-4 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover disabled:opacity-50 transition-colors cursor-pointer">
            <Check :size="13" /> Add event
          </button>
          <button @click="cancelForm" class="px-3 py-1.5 bg-surface-hover text-text-secondary text-[12px] rounded-md hover:bg-border cursor-pointer">Cancel</button>
        </div>
      </div>
    </Transition>

    <!-- Agenda by day -->
    <div class="space-y-3">
      <div v-for="d in days" :key="d.label" class="bg-surface rounded-lg border border-border overflow-hidden">
        <div class="px-3 py-1.5 bg-surface-hover text-[11px] font-semibold uppercase tracking-wide text-text-secondary border-b border-border">
          {{ d.label }}
        </div>
        <div v-if="d.items.length === 0" class="px-3 py-2 text-[12px] text-text-muted italic">—</div>
        <div v-else>
          <div v-for="(it, idx) in d.items" :key="idx"
            class="flex items-start gap-2.5 px-3 py-2 border-t border-border/50 first:border-t-0 group">
            <span class="shrink-0 w-1.5 h-1.5 rounded-full mt-1.5" :style="{ background: it.color || 'var(--color-accent)' }" />
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <span class="text-[13px] font-medium text-text-primary truncate">{{ it.title }}</span>
                <Repeat v-if="it.is_recurring" :size="11" class="text-text-muted shrink-0" />
              </div>
              <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-0.5 text-[11px] text-text-muted">
                <span class="flex items-center gap-1"><Clock :size="10" /> {{ fmtTime(it.start_at, it.all_day) }}</span>
                <span v-if="it.location" class="flex items-center gap-1"><MapPin :size="10" /> {{ it.location }}</span>
              </div>
            </div>
            <button @click="store.deleteEvent(it.event_id)"
              class="shrink-0 p-1 rounded text-text-muted hover:text-danger hover:bg-danger/10 opacity-0 group-hover:opacity-100 transition-all cursor-pointer">
              <X :size="12" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <Transition name="toast">
      <div v-if="toast"
        class="fixed bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 px-3.5 py-2 rounded-lg border text-[12px] shadow-lg z-50"
        :class="toast.type === 'success' ? 'bg-green-900/90 border-green-700 text-green-100' : 'bg-red-900/90 border-red-700 text-red-100'">
        <CheckCircle2 v-if="toast.type === 'success'" :size="14" />
        <AlertCircle v-else :size="14" />
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
