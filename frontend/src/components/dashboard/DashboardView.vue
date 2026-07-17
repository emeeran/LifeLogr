<script setup lang="ts">
/**
 * DashboardView — compact, real-time app landing page.
 *
 *   • Slim sticky hero bar: greeting + one-line summary, live clock,
 *     "updated Ns ago", manual refresh, and a live-updates pause toggle.
 *   • Dense KPI strip (events / tasks / unread / streak).
 *   • Schedule (today + next 7 days, recurring-aware) + Tasks (overdue first,
 *     quick-add, inline complete).
 *   • Inbox, account-wise: each mailbox with unread count + recent unread.
 *
 * "Real-time" is delivered by background polling: a 1s ticker drives the clock
 * and the "updated … ago" label; a 30s poll re-fetches everything silently when
 * live updates are on and the tab is visible. Data comes from existing APIs —
 * no backend changes.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { useRouter } from 'vue-router'
import {
  CalendarDays, ListTodo, Mail, Flame, RefreshCw, ArrowRight,
  AlertCircle, Plus, Inbox, Settings as SettingsIcon, Repeat, CheckCircle2, Pause, Play,
} from 'lucide-vue-next'
import { useUiStore } from '../../stores/ui'
import { usePlannerStore } from '../../stores/planner'
import { useEmailStore } from '../../stores/email'
import * as plannerApi from '../../api/planner'
import * as emailApi from '../../api/email'
import * as analyticsApi from '../../api/analytics'
import type {
  AgendaItem, TaskResponse, TaskPriority, EmailAccountResponse, EmailMessageListResponse,
  OverviewResponse,
} from '../../types'

const ui = useUiStore()
const router = useRouter()
const planner = usePlannerStore()
const emailStore = useEmailStore()

// ── State ────────────────────────────────────────────────────────────────────
const loading = ref(true)
const refreshing = ref(false)
const lastUpdated = ref<Date | null>(null)
const liveOn = useLocalStorage<boolean>('lifelogr-dashboard-live', true)

// Reactive "now" — bumped every second to drive the clock + "updated ago" label.
const now = ref(new Date())

const agenda = ref<AgendaItem[]>([])
const allTasks = ref<TaskResponse[]>([])
const overview = ref<OverviewResponse | null>(null)

interface AccountSummary {
  account: EmailAccountResponse
  unreadTotal: number
  recent: EmailMessageListResponse[]
  error?: string
}
const accountSummaries = ref<AccountSummary[]>([])

const quickTask = ref('')
const addingTask = ref(false)
const defaultListId = computed(() => planner.taskLists[0]?.id ?? null)

// Flash the unread stat when it changes (real-time cue).
const bump = ref(false)

// ── Date / time helpers ──────────────────────────────────────────────────────
function startOfDay(d: Date) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
function formatTime(s: string) {
  return new Date(s).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}
function dayDiff(s: string) {
  return Math.round((startOfDay(new Date(s)).getTime() - startOfDay(now.value).getTime()) / 86_400_000)
}
function dayLabel(s: string) {
  const diff = dayDiff(s)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (diff > 1 && diff < 7) return new Date(s).toLocaleDateString(undefined, { weekday: 'short' })
  return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
function dueLabel(s: string) {
  const diff = dayDiff(s)
  if (diff < 0) return `${Math.abs(diff)}d over`
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tom'
  if (diff < 7) return new Date(s).toLocaleDateString(undefined, { weekday: 'short' })
  return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
function relTime(s: string | null) {
  if (!s) return ''
  const diff = (now.value.getTime() - new Date(s).getTime()) / 1000
  if (diff < 60) return 'now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`
  if (diff < 172800) return 'Yest'
  return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// ── Hero computeds ───────────────────────────────────────────────────────────
const greeting = computed(() => {
  const h = now.value.getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
})
const clock = computed(() =>
  now.value.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', second: '2-digit' }),
)
const updatedLabel = computed(() => {
  if (refreshing.value) return 'updating…'
  if (!lastUpdated.value) return ''
  const s = Math.floor((now.value.getTime() - lastUpdated.value.getTime()) / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `updated ${s}s ago`
  const m = Math.floor(s / 60)
  return m < 60 ? `updated ${m}m ago` : `updated ${Math.floor(m / 60)}h ago`
})

// ── Derived data ─────────────────────────────────────────────────────────────
const todayEvents = computed(() => agenda.value.filter((a) => dayDiff(a.start_at) <= 0))
const upcomingEvents = computed(() =>
  agenda.value.filter((a) => dayDiff(a.start_at) > 0).slice(0, 5),
)
const openTasks = computed(() => allTasks.value.filter((t) => !t.is_completed))
const completedTasks = computed(() => allTasks.value.filter((t) => t.is_completed))
const overdueTasks = computed(() =>
  openTasks.value.filter((t) => t.due_date && dayDiff(t.due_date) < 0),
)
const dueSoonTasks = computed(() =>
  openTasks.value
    .filter((t) => t.due_date && dayDiff(t.due_date) >= 0)
    .sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1))
    .slice(0, 6),
)
const tasksToShow = computed(() => [...overdueTasks.value, ...dueSoonTasks.value])
const tasksProgress = computed(() => {
  const total = allTasks.value.length
  return total ? Math.round((completedTasks.value.length / total) * 100) : 0
})
const totalUnread = computed(() => accountSummaries.value.reduce((s, a) => s + a.unreadTotal, 0))
const connectedAccounts = computed(() => accountSummaries.value.length)

const summaryLine = computed(() => {
  const parts: string[] = []
  const te = todayEvents.value.length
  if (te) parts.push(`${te} event${te > 1 ? 's' : ''}`)
  const ot = openTasks.value.length
  if (ot) parts.push(`${ot} task${ot > 1 ? 's' : ''}`)
  const od = overdueTasks.value.length
  if (od) parts.push(`${od} overdue`)
  const ur = totalUnread.value
  if (ur) parts.push(`${ur} unread`)
  if (!parts.length) return 'All caught up — nothing pending.'
  return parts.join(' · ')
})

const priorityStyle: Record<TaskPriority, string> = {
  high: 'bg-rose-500/15 text-rose-400',
  medium: 'bg-amber-500/15 text-amber-400',
  low: 'bg-sky-500/15 text-sky-400',
}

// Flash on unread change.
let prevUnread = -1
watch(totalUnread, (n) => {
  if (prevUnread >= 0 && n !== prevUnread) {
    bump.value = true
    setTimeout(() => (bump.value = false), 700)
  }
  prevUnread = n
})

// ── Actions ──────────────────────────────────────────────────────────────────
async function addQuickTask() {
  const title = quickTask.value.trim()
  if (!title || defaultListId.value == null || addingTask.value) return
  addingTask.value = true
  try {
    await plannerApi.createTask({ title, list_id: defaultListId.value })
    quickTask.value = ''
    allTasks.value = await plannerApi.listTasks({ include_completed: true })
  } finally {
    addingTask.value = false
  }
}

async function toggleTask(t: TaskResponse) {
  const next = !t.is_completed
  t.is_completed = next
  try {
    await plannerApi.setTaskCompleted(t.id, next)
  } catch {
    t.is_completed = !next
  }
}

function goPlanner() { ui.setView('planner'); router.push('/planner') }
function goSettings() { ui.setView('settings'); router.push('/settings') }
function goEmail(accountId?: number) {
  ui.setView('email')
  if (accountId != null) void emailStore.selectAccount(accountId)
  router.push('/email')
}

async function loadEmailSummaries(accs: EmailAccountResponse[]) {
  accountSummaries.value = await Promise.all(
    accs.map(async (account): Promise<AccountSummary> => {
      try {
        const res = await emailApi.listMessages({
          account_id: account.id, unread_only: true, exclude_spam: true, limit: 4,
        })
        return { account, unreadTotal: res.total, recent: res.items }
      } catch (e: any) {
        return { account, unreadTotal: 0, recent: [], error: e?.message || 'unavailable' }
      }
    }),
  )
}

/** Full data refresh. `silent` = background poll (no spinner, no error surfacing). */
async function loadAll(silent = false) {
  if (!silent) refreshing.value = true
  try {
    const from = startOfDay(new Date())
    const to = new Date(from)
    to.setDate(to.getDate() + 7)

    const [agendaRes, tasksRes, , accountsRes, overviewRes] = await Promise.allSettled([
      plannerApi.getAgenda(from, to),
      plannerApi.listTasks({ include_completed: true }),
      planner.fetchTaskLists(),
      emailApi.listAccounts(),
      analyticsApi.getOverview(),
    ])

    if (agendaRes.status === 'fulfilled') agenda.value = agendaRes.value.items
    if (tasksRes.status === 'fulfilled') allTasks.value = tasksRes.value
    if (accountsRes.status === 'fulfilled') await loadEmailSummaries(accountsRes.value)
    if (overviewRes.status === 'fulfilled') overview.value = overviewRes.value
  } finally {
    loading.value = false
    if (!silent) refreshing.value = false
    lastUpdated.value = new Date()
  }
}

// ── Real-time polling ────────────────────────────────────────────────────────
let tickId: number | undefined
let pollId: number | undefined

function onVisible() {
  if (document.visibilityState === 'visible' && liveOn.value) loadAll(true)
}

function startPolling() {
  stopPolling()
  tickId = window.setInterval(() => { now.value = new Date() }, 1000)
  pollId = window.setInterval(() => {
    if (!liveOn.value || document.visibilityState === 'hidden') return
    loadAll(true)
  }, 30_000)
}
function stopPolling() {
  if (tickId) window.clearInterval(tickId)
  if (pollId) window.clearInterval(pollId)
  tickId = pollId = undefined
}

onMounted(() => {
  ui.setView('dashboard')
  loadAll()
  startPolling()
  document.addEventListener('visibilitychange', onVisible)
})
onUnmounted(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', onVisible)
})

function initialsOf(s: string) {
  const parts = s.trim().split(/[\s@.]+/).filter(Boolean)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '?'
}
</script>

<template>
  <div class="dashboard flex h-full flex-col overflow-hidden">
    <!-- ── Slim hero bar (sticky) ────────────────────────────────────────── -->
    <header class="hero-bar flex items-center gap-3 border-b border-border px-4 py-2">
      <span class="live" :class="{ off: !liveOn }" :title="liveOn ? 'Live updates on' : 'Live updates paused'">
        <span class="pulse" />{{ liveOn ? 'LIVE' : 'PAUSED' }}
      </span>
      <div class="min-w-0 flex-1">
        <span class="truncate text-[13px] font-semibold text-text-primary">{{ greeting }}.</span>
        <span class="ml-1.5 hidden truncate text-[12px] text-text-muted sm:inline">· {{ summaryLine }}</span>
      </div>
      <span class="clock">{{ clock }}</span>
      <span class="hidden w-[92px] text-right text-[10.5px] text-text-muted md:inline">{{ updatedLabel }}</span>
      <button
        class="icon-btn"
        :class="{ 'pointer-events-none opacity-60': refreshing }"
        title="Refresh now"
        @click="loadAll(false)"
      >
        <RefreshCw :size="14" :class="refreshing ? 'animate-spin' : ''" />
      </button>
      <button
        class="icon-btn"
        :class="{ 'text-emerald-400': liveOn }"
        :title="liveOn ? 'Pause live updates' : 'Resume live updates'"
        @click="liveOn = !liveOn"
      >
        <component :is="liveOn ? Pause : Play" :size="14" />
      </button>
    </header>

    <!-- ── Scroll body ───────────────────────────────────────────────────── -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <div class="mx-auto max-w-7xl px-4 py-3">
        <!-- KPI strip -->
        <div class="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <button class="stat" @click="goPlanner">
            <span class="chip bg-accent/15 text-accent"><CalendarDays :size="15" /></span>
            <span class="stat-body">
              <span class="stat-num">{{ todayEvents.length }}</span>
              <span class="stat-label">Events today · {{ upcomingEvents.length }} up</span>
            </span>
          </button>
          <button class="stat" @click="goPlanner">
            <span class="chip bg-emerald-500/15 text-emerald-400"><ListTodo :size="15" /></span>
            <span class="stat-body">
              <span class="stat-num">{{ openTasks.length }}</span>
              <span class="stat-label" :class="overdueTasks.length ? 'text-rose-400' : ''">
                {{ overdueTasks.length ? `${overdueTasks.length} overdue` : `${tasksProgress}% done` }}
              </span>
            </span>
          </button>
          <button class="stat" @click="goEmail()">
            <span class="chip bg-amber-500/15 text-amber-400"><Mail :size="15" /></span>
            <span class="stat-body">
              <span class="stat-num" :class="{ bump }">{{ totalUnread }}</span>
              <span class="stat-label">Unread · {{ connectedAccounts }} accts</span>
            </span>
          </button>
          <div class="stat cursor-default">
            <span class="chip bg-rose-500/15 text-rose-400"><Flame :size="15" /></span>
            <span class="stat-body">
              <span class="stat-num">{{ overview?.current_streak ?? 0 }}</span>
              <span class="stat-label">Day streak · best {{ overview?.longest_streak ?? 0 }}</span>
            </span>
          </div>
        </div>

        <!-- Main grid -->
        <div class="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
          <!-- Left column -->
          <div class="space-y-3 lg:col-span-2">
            <!-- Schedule -->
            <section class="panel">
              <div class="panel-head">
                <h2><CalendarDays :size="13" class="text-accent" /> Schedule</h2>
                <button class="link" @click="goPlanner">Planner <ArrowRight :size="10" /></button>
              </div>
              <div class="p-2">
                <ul class="space-y-0.5">
                  <li v-if="todayEvents.length" class="group-label">Today</li>
                  <li v-for="e in todayEvents" :key="e.event_id" class="event-row" @click="goPlanner">
                    <span class="time">{{ e.all_day ? 'all day' : formatTime(e.start_at) }}</span>
                    <span class="dot" :style="{ background: e.color || 'var(--color-accent)' }" />
                    <div class="min-w-0 flex-1">
                      <p class="flex items-center gap-1 truncate text-[12px] font-medium text-text-primary">
                        <Repeat v-if="e.is_recurring" :size="10" class="shrink-0 text-text-muted" />{{ e.title }}
                      </p>
                      <p v-if="e.location" class="truncate text-[10.5px] text-text-muted">{{ e.location }}</p>
                    </div>
                  </li>
                  <li v-if="upcomingEvents.length" class="group-label mt-1.5">Coming up</li>
                  <li v-for="e in upcomingEvents" :key="e.event_id" class="event-row" @click="goPlanner">
                    <span class="time">{{ dayLabel(e.start_at) }}</span>
                    <span class="dot" :style="{ background: e.color || 'var(--color-accent)' }" />
                    <div class="min-w-0 flex-1">
                      <p class="flex items-center gap-1 truncate text-[12px] font-medium text-text-primary">
                        <Repeat v-if="e.is_recurring" :size="10" class="shrink-0 text-text-muted" />{{ e.title }}
                      </p>
                      <p v-if="!e.all_day" class="truncate text-[10.5px] text-text-muted">{{ formatTime(e.start_at) }}</p>
                    </div>
                  </li>
                </ul>
                <div v-if="!todayEvents.length && !upcomingEvents.length" class="empty">
                  <CalendarDays :size="20" class="text-text-muted/60" />
                  <p class="text-[12px] font-medium text-text-secondary">No upcoming events</p>
                  <p class="text-[10.5px] text-text-muted">Clear for the next 7 days.</p>
                </div>
              </div>
            </section>

            <!-- Tasks -->
            <section class="panel">
              <div class="panel-head">
                <h2>
                  <ListTodo :size="13" class="text-emerald-400" /> Tasks
                  <span v-if="openTasks.length" class="badge bg-emerald-500/15 text-emerald-400">{{ openTasks.length }}</span>
                </h2>
                <button class="link" @click="goPlanner">All <ArrowRight :size="10" /></button>
              </div>
              <div class="border-b border-border px-2 py-1.5">
                <form @submit.prevent="addQuickTask">
                  <div class="relative">
                    <Plus :size="12" class="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
                    <input
                      v-model="quickTask"
                      :placeholder="defaultListId == null ? 'Create a task list in Planner first…' : 'Add a task, press Enter…'"
                      :disabled="defaultListId == null"
                      class="quick-input"
                    />
                  </div>
                </form>
              </div>
              <div class="p-2">
                <ul v-if="tasksToShow.length" class="space-y-0.5">
                  <li v-for="t in tasksToShow" :key="t.id" class="task-row">
                    <button class="check" :class="{ done: t.is_completed }" @click="toggleTask(t)">
                      <CheckCircle2 v-if="t.is_completed" :size="13" />
                    </button>
                    <span class="min-w-0 flex-1 truncate text-[12px]" :class="t.is_completed ? 'text-text-muted line-through' : 'text-text-primary'">{{ t.title }}</span>
                    <span v-if="t.priority" class="badge shrink-0 capitalize" :class="priorityStyle[t.priority]">{{ t.priority }}</span>
                    <span v-if="t.due_date" class="shrink-0 text-[10.5px] font-medium" :class="dayDiff(t.due_date) < 0 && !t.is_completed ? 'text-rose-400' : 'text-text-muted'">{{ dueLabel(t.due_date) }}</span>
                  </li>
                </ul>
                <div v-else class="empty">
                  <CheckCircle2 :size="20" class="text-emerald-400/60" />
                  <p class="text-[12px] font-medium text-text-secondary">All clear</p>
                  <p class="text-[10.5px] text-text-muted">No pending or overdue tasks.</p>
                </div>
              </div>
            </section>
          </div>

          <!-- Right column: inbox -->
          <div>
            <section class="panel">
              <div class="panel-head">
                <h2>
                  <Mail :size="13" class="text-amber-400" /> Inbox
                  <span v-if="totalUnread" class="badge bg-amber-500/15 text-amber-400">{{ totalUnread }}</span>
                </h2>
                <button class="link" @click="goEmail()">Email <ArrowRight :size="10" /></button>
              </div>

              <div v-if="!connectedAccounts" class="empty m-2">
                <Inbox :size="20" class="text-text-muted/60" />
                <p class="text-[12px] font-medium text-text-secondary">No mailboxes connected</p>
                <button class="btn-accent mt-1" @click="goSettings"><SettingsIcon :size="11" /> Connect in Settings</button>
              </div>

              <div v-else class="divide-y divide-border">
                <div v-for="s in accountSummaries" :key="s.account.id" class="account-block" @click="goEmail(s.account.id)">
                  <div class="flex items-center gap-2 px-2.5 py-2">
                    <span class="avatar">{{ initialsOf(s.account.label || s.account.email_address) }}</span>
                    <div class="min-w-0 flex-1">
                      <p class="truncate text-[12px] font-semibold text-text-primary">{{ s.account.label }}</p>
                      <p class="truncate text-[10.5px] text-text-muted">{{ s.account.email_address }}</p>
                    </div>
                    <span v-if="s.error" class="text-[10px] text-rose-400" :title="s.error"><AlertCircle :size="11" /></span>
                    <span v-else class="badge shrink-0" :class="s.unreadTotal ? 'bg-amber-500/15 text-amber-400' : 'bg-surface-hover text-text-muted'">{{ s.unreadTotal }}</span>
                  </div>
                  <ul v-if="s.recent.length" class="pb-1.5">
                    <li v-for="m in s.recent.slice(0, 3)" :key="m.id" class="msg-row">
                      <span class="unread-dot" />
                      <div class="min-w-0 flex-1">
                        <p class="truncate text-[11.5px] font-medium text-text-primary">{{ m.from_name || m.from_address }}</p>
                        <p class="truncate text-[10.5px] text-text-muted">{{ m.subject || '(no subject)' }}</p>
                      </div>
                      <span class="shrink-0 text-[10px] text-text-muted">{{ relTime(m.sent_at) }}</span>
                    </li>
                  </ul>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── Hero bar ────────────────────────────────────────────────────────────── */
.hero-bar {
  background:
    linear-gradient(90deg, color-mix(in srgb, var(--color-accent) 9%, transparent), transparent 30%),
    var(--color-surface);
}
.live {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  flex-shrink: 0;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.09em;
  color: #10b981;
}
.live.off { color: var(--color-text-muted); }
.pulse {
  width: 7px; height: 7px; border-radius: 999px;
  background: #10b981;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.55);
  animation: pulse 1.8s infinite;
}
.live.off .pulse { background: var(--color-text-muted); animation: none; }
@keyframes pulse {
  0%   { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.55); }
  70%  { box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
.clock {
  flex-shrink: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px; height: 28px;
  flex-shrink: 0;
  border-radius: 0.45rem;
  border: 1px solid var(--color-border);
  background: var(--color-surface-hover);
  color: var(--color-text-muted);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.icon-btn:hover { color: var(--color-text-primary); border-color: var(--color-accent); }

/* ── Panels ──────────────────────────────────────────────────────────────── */
.panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0.7rem;
  overflow: hidden;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.45rem 0.7rem;
  border-bottom: 1px solid var(--color-border);
}
.panel-head h2 {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.link {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
  font-size: 10.5px;
  font-weight: 500;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: color 0.15s;
}
.link:hover { color: var(--color-accent); }
.group-label {
  padding: 0.2rem 0.5rem 0.1rem;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
.badge {
  display: inline-flex;
  align-items: center;
  padding: 0 0.35rem;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 600;
  line-height: 1.6;
}

/* ── KPI strip ───────────────────────────────────────────────────────────── */
.stat {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.55rem 0.65rem;
  text-align: left;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0.6rem;
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease;
}
.stat:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border));
}
.stat .chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px; height: 26px;
  border-radius: 0.45rem;
  flex-shrink: 0;
}
.stat-body { display: flex; flex-direction: column; line-height: 1.15; min-width: 0; }
.stat-num {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--color-text-primary);
  transition: color 0.2s, transform 0.2s;
}
.stat-num.bump { color: var(--color-accent); transform: scale(1.18); }
.stat-label {
  font-size: 10px;
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Schedule rows ───────────────────────────────────────────────────────── */
.event-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.32rem 0.5rem;
  border-radius: 0.4rem;
  cursor: pointer;
  transition: background 0.15s;
}
.event-row:hover { background: var(--color-surface-hover); }
.event-row .time {
  flex-shrink: 0;
  width: 50px;
  font-size: 10px;
  font-weight: 600;
  color: var(--color-text-muted);
}
.event-row .dot {
  flex-shrink: 0;
  width: 7px; height: 7px;
  border-radius: 999px;
}

/* ── Task rows ───────────────────────────────────────────────────────────── */
.quick-input {
  width: 100%;
  border-radius: 0.4rem;
  border: 1px solid var(--color-border);
  background: var(--color-surface-hover);
  padding: 0.3rem 0.5rem 0.3rem 1.5rem;
  font-size: 11.5px;
  color: var(--color-text-primary);
  outline: none;
  transition: border-color 0.15s;
}
.quick-input::placeholder { color: var(--color-text-muted); }
.quick-input:focus { border-color: var(--color-accent); }
.quick-input:disabled { opacity: 0.6; }

.task-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.32rem 0.4rem;
  border-radius: 0.4rem;
  transition: background 0.15s;
}
.task-row:hover { background: var(--color-surface-hover); }
.check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px; height: 14px;
  flex-shrink: 0;
  border-radius: 999px;
  border: 1.5px solid var(--color-text-muted);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.check:hover { border-color: var(--color-accent); }
.check.done { border-color: var(--color-accent); background: var(--color-accent); color: #fff; }

/* ── Inbox ───────────────────────────────────────────────────────────────── */
.account-block { cursor: pointer; transition: background 0.15s; }
.account-block:hover { background: var(--color-surface-hover); }
.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px; height: 26px;
  flex-shrink: 0;
  border-radius: 0.45rem;
  font-size: 10px;
  font-weight: 700;
  color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 16%, transparent);
}
.msg-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.22rem 0.7rem 0.22rem 2.65rem;
  transition: background 0.15s;
}
.msg-row:hover { background: var(--color-surface-hover); }
.unread-dot {
  flex-shrink: 0;
  width: 5px; height: 5px;
  border-radius: 999px;
  background: var(--color-accent);
}

/* ── Empty states ────────────────────────────────────────────────────────── */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.15rem;
  padding: 1.1rem 0.75rem;
  text-align: center;
}
.btn-accent {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.6rem;
  border-radius: 0.4rem;
  font-size: 10.5px;
  font-weight: 600;
  color: #fff;
  background: var(--color-accent);
  cursor: pointer;
  transition: background 0.15s;
}
.btn-accent:hover { background: color-mix(in srgb, var(--color-accent) 85%, #000); }
</style>
