<script setup lang="ts">
/**
 * DashboardView — compact, real-time app landing page.
 *
 *   • Slim sticky hero bar: greeting + one-line summary, live clock,
 *     "updated Ns ago", manual refresh, and a live-updates pause toggle.
 *   • Dense KPI strip (unread / streak).
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
  Mail, Flame, RefreshCw, ArrowRight,
  AlertCircle, Inbox, Settings as SettingsIcon, Pause, Play,
} from 'lucide-vue-next'
import { useUiStore } from '../../stores/ui'
import { useEmailStore } from '../../stores/email'
import * as emailApi from '../../api/email'
import * as analyticsApi from '../../api/analytics'
import type {
  EmailAccountResponse, EmailMessageListResponse,
  OverviewResponse,
} from '../../types'

const ui = useUiStore()
const router = useRouter()
const emailStore = useEmailStore()

// ── State ────────────────────────────────────────────────────────────────────
const loading = ref(true)
const refreshing = ref(false)
const lastUpdated = ref<Date | null>(null)
const liveOn = useLocalStorage<boolean>('lifelogr-dashboard-live', true)

// Reactive "now" — bumped every second to drive the clock + "updated ago" label.
const now = ref(new Date())

const overview = ref<OverviewResponse | null>(null)

interface AccountSummary {
  account: EmailAccountResponse
  unreadTotal: number
  recent: EmailMessageListResponse[]
  error?: string
}
const accountSummaries = ref<AccountSummary[]>([])

// Flash the unread stat when it changes (real-time cue).
const bump = ref(false)

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
const totalUnread = computed(() => accountSummaries.value.reduce((s, a) => s + a.unreadTotal, 0))
const connectedAccounts = computed(() => accountSummaries.value.length)

const summaryLine = computed(() => {
  const ur = totalUnread.value
  if (ur) return `${ur} unread`
  return 'All caught up — nothing pending.'
})

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
    const [accountsRes, overviewRes] = await Promise.allSettled([
      emailApi.listAccounts(),
      analyticsApi.getOverview(),
    ])

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
        <div class="grid grid-cols-2 gap-2.5">
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

        <!-- Inbox -->
        <div class="mt-3 grid grid-cols-1 gap-3">
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
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
  text-align: center;
}
.msg-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.6rem;
}
.unread-dot {
  width: 6px; height: 6px;
  flex-shrink: 0;
  border-radius: 999px;
  background: var(--color-accent);
}
.btn-accent {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.3rem 0.6rem;
  border-radius: 0.4rem;
  background: color-mix(in srgb, var(--color-accent) 18%, transparent);
  color: var(--color-accent);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  border: none;
}
</style>
