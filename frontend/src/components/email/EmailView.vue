<script setup lang="ts">
/**
 * EmailView — IMAP/SMTP mail client (EPIM/Outlook-style three-pane layout).
 *
 *   ┌──────────────────────── toolbar ────────────────────────┐
 *   │ New │ Reply │ Reply All │ Forward │ Send/Recv │ Delete │ ⚙ │
 *   ├── Folder rail ──┬─ Message list (date-grouped) ─┬─ Reader ─┤
 *   │ account header  │  TODAY / YESTERDAY …          │ From/To │
 *   │ collapsible     │  avatar · sender · subject    │ body    │
 *   │ folders + tree  │  snippet · time · ★           │ quick   │
 *   │ unread badges   │  … · Load more                │ reply   │
 *
 * Folder + spam counts refresh on a 60s poll so badges stay live. The Spam
 * button opens a block-sender chooser (move to Junk / delete, for existing +
 * future mail). HTML bodies render in a sandboxed iframe; config is in Settings.
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useLocalStorage } from '@vueuse/core'
import { useEmailStore } from '../../stores/email'
import * as emailApi from '../../api/email'
import type {
  EmailFolderResponse,
  EmailMessageListResponse,
  TempAttachmentResponse,
} from '../../types'
import {
  Mail, Inbox, Send, Star, Trash2, RefreshCw, Plus, Settings, X, Search,
  Reply, ReplyAll, Forward, Paperclip, Download, AlertCircle, CheckCircle2,
  Folder as FolderIcon, Archive, Ban, FileEdit, MailOpen, ChevronDown,
  ChevronRight, ShieldAlert, ListTodo, CheckSquare, Square, User, Globe,
} from 'lucide-vue-next'
import { createTask } from '../../api/planner'

const store = useEmailStore()
const router = useRouter()
const settingsTab = useLocalStorage<string>('lifelogr-settings-tab', 'general')

function goToSettings() {
  settingsTab.value = 'email'
  router.push('/settings')
}

// ── Toast ──
const toast = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error' | 'info', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3500)
}

// ── Compose modal ──
const showCompose = ref(false)
const showCc = ref(false)
const compose = ref({
  to: '', cc: '', subject: '', body: '',
  in_reply_to_message_id: null as number | null,
  attachments: [] as TempAttachmentResponse[],
})
const sending = ref(false)
const attachInput = ref<HTMLInputElement | null>(null)
const composeToRef = ref<HTMLInputElement | null>(null)

function openCompose(replyTo?: EmailMessageListResponse, mode: 'reply' | 'replyall' | 'forward' = 'reply') {
  compose.value = { to: '', cc: '', subject: '', body: '', in_reply_to_message_id: null, attachments: [] }
  showCc.value = false
  if (replyTo) {
    if (mode === 'forward') {
      compose.value.subject = replyTo.subject?.startsWith('Fwd:') ? replyTo.subject : `Fwd: ${replyTo.subject ?? ''}`
      compose.value.body =
        `\n\n---------- Forwarded message ----------\n` +
        `From: ${replyTo.from_name || replyTo.from_address}\n` +
        `Subject: ${replyTo.subject ?? ''}\n\n${replyTo.snippet ?? ''}`
    } else {
      compose.value.to = replyTo.from_address
      if (mode === 'replyall') {
        const me = activeAccount.value?.email_address.toLowerCase()
        const extras = (replyTo.to_addresses || []).map((t) => t.address)
          .filter((a) => a.toLowerCase() !== me)
        if (extras.length) {
          compose.value.cc = extras.join(', ')
          showCc.value = true
        }
      }
      compose.value.subject = replyTo.subject?.startsWith('Re:') ? replyTo.subject : `Re: ${replyTo.subject ?? ''}`
      compose.value.in_reply_to_message_id = replyTo.id
    }
  }
  showCompose.value = true
  nextTick(() => composeToRef.value?.focus())
}

async function onAttachFiles(e: Event) {
  const target = e.target as HTMLInputElement
  const files = Array.from(target.files ?? [])
  for (const file of files) {
    try {
      const meta = await emailApi.uploadTempAttachment(file)
      compose.value.attachments.push(meta)
    } catch {
      showToast('error', `Could not attach ${file.name}`)
    }
  }
  target.value = ''
}

function removeAttachment(id: string) {
  compose.value.attachments = compose.value.attachments.filter((a) => a.id !== id)
}

function parseAddresses(s: string): string[] {
  return s.split(',').map((p) => p.trim()).filter(Boolean)
}

async function sendCompose(asDraft = false) {
  if (!activeAccount.value) return
  const to = parseAddresses(compose.value.to)
  if (!asDraft && !to.length) {
    showToast('error', 'Add at least one recipient')
    return
  }
  sending.value = true
  try {
    const res = asDraft
      ? await emailApi.saveDraft({
          account_id: activeAccount.value.id, to, cc: parseAddresses(compose.value.cc) || null,
          subject: compose.value.subject, text_body: compose.value.body,
          attachment_ids: compose.value.attachments.map((a) => a.id),
        })
      : await emailApi.sendMessage({
          account_id: activeAccount.value.id, to, cc: parseAddresses(compose.value.cc) || null,
          subject: compose.value.subject, text_body: compose.value.body,
          in_reply_to_message_id: compose.value.in_reply_to_message_id,
          attachment_ids: compose.value.attachments.map((a) => a.id),
        })
    if (res.success) {
      showToast('success', asDraft ? 'Draft saved' : 'Message sent')
      showCompose.value = false
    } else {
      showToast('error', res.error ?? 'Send failed')
    }
  } finally {
    sending.value = false
  }
}

// ── Quick reply (inline, at the bottom of the reader) ──
const quickReply = ref('')
async function sendQuickReply() {
  if (!activeAccount.value || !store.selectedMessage || !quickReply.value.trim()) return
  sending.value = true
  try {
    const subj = store.selectedMessage.subject?.startsWith('Re:')
      ? store.selectedMessage.subject : `Re: ${store.selectedMessage.subject ?? ''}`
    const res = await emailApi.sendMessage({
      account_id: activeAccount.value.id,
      to: [store.selectedMessage.from_address],
      cc: null,
      subject: subj,
      text_body: quickReply.value,
      in_reply_to_message_id: store.selectedMessage.id,
    })
    if (res.success) { showToast('success', 'Reply sent'); quickReply.value = '' }
    else showToast('error', res.error ?? 'Send failed')
  } finally {
    sending.value = false
  }
}
function onQuickReplyKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); sendQuickReply() }
}

// ── Folder / message helpers ──
const activeAccount = computed(() => store.accounts.find((a) => a.id === store.activeAccountId) ?? null)

const FOLDER_META: Record<string, { icon: typeof Inbox; label: string; color: string }> = {
  inbox: { icon: Inbox, label: 'Inbox', color: 'text-sky-500' },
  sent: { icon: Send, label: 'Sent', color: 'text-violet-500' },
  drafts: { icon: FileEdit, label: 'Drafts', color: 'text-amber-500' },
  trash: { icon: Trash2, label: 'Trash', color: 'text-rose-500' },
  junk: { icon: Ban, label: 'Junk', color: 'text-orange-500' },
  archive: { icon: Archive, label: 'Archive', color: 'text-teal-500' },
}
function folderIcon(f: EmailFolderResponse) {
  return (f.special_use && FOLDER_META[f.special_use]?.icon) || FolderIcon
}
function folderColor(f: EmailFolderResponse) {
  return (f.special_use && FOLDER_META[f.special_use]?.color) || 'text-text-muted'
}
function folderLabel(f: EmailFolderResponse) {
  if (f.special_use && FOLDER_META[f.special_use]?.label) return FOLDER_META[f.special_use].label
  // For nested folders show the last path segment as the leaf label.
  return f.display_name || (f.folder_name.includes('/') ? f.folder_name.split('/').pop()! : f.folder_name)
}

// ── Collapsible folder tree ──
// The "Folders" section collapses as a whole; non-special folders that share a
// parent path (e.g. "[Gmail]/Sent Mail") are grouped under an expandable node.
const foldersOpen = useLocalStorage<boolean>('lifelogr-email-folders-open', true)
const groupOpenState = useLocalStorage<Record<string, boolean>>('lifelogr-email-folder-group-open', {})
function isGroupOpen(key: string) { return groupOpenState.value[key] !== false }
function toggleGroup(key: string) {
  groupOpenState.value = { ...groupOpenState.value, [key]: !isGroupOpen(key) }
}

type FolderNode =
  | { type: 'leaf'; folder: EmailFolderResponse }
  | { type: 'group'; key: string; label: string; folders: EmailFolderResponse[] }

const folderTree = computed<FolderNode[]>(() => {
  const nodes: FolderNode[] = []
  const special = store.folders.filter((f) => f.special_use)
  const plain = store.folders.filter((f) => !f.special_use)
  for (const f of special) nodes.push({ type: 'leaf', folder: f })

  const groups = new Map<string, EmailFolderResponse[]>()
  const orphans: EmailFolderResponse[] = []
  for (const f of plain) {
    const slash = f.folder_name.lastIndexOf('/')
    if (slash > 0) {
      const parent = f.folder_name.slice(0, slash)
      if (!groups.has(parent)) groups.set(parent, [])
      groups.get(parent)!.push(f)
    } else {
      orphans.push(f)
    }
  }
  for (const f of orphans) nodes.push({ type: 'leaf', folder: f })
  for (const [parent, fs] of groups) {
    nodes.push({ type: 'group', key: parent, label: parent.split('/').pop() || parent, folders: fs })
  }
  return nodes
})

function sender(msg: EmailMessageListResponse) {
  return msg.from_name || msg.from_address
}
// Deterministic colour + initials for a sender's avatar circle.
const AVATAR_COLORS = [
  'bg-rose-500', 'bg-orange-500', 'bg-amber-500', 'bg-lime-500', 'bg-emerald-500',
  'bg-teal-500', 'bg-cyan-500', 'bg-sky-500', 'bg-indigo-500', 'bg-violet-500',
  'bg-fuchsia-500', 'bg-pink-500',
]
function avatarColor(seed: string): string {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}
function initialsOf(s: string): string {
  const clean = s.replace(/[<>"']/g, '').trim()
  const parts = clean.split(/[\s@._]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return clean.slice(0, 2).toUpperCase() || '?'
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const sameYear = d.getFullYear() === now.getFullYear()
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: sameYear ? undefined : 'numeric' })
}
function formatFullDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(+d) ? iso : d.toLocaleString([], {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function dateBucket(iso: string | null): string {
  if (!iso) return 'No date'
  const d = new Date(iso)
  if (isNaN(+d)) return 'No date'
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const dd = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const days = Math.round((today.getTime() - dd.getTime()) / 86400000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return 'This week'
  return d.toLocaleDateString([], { month: 'long', year: 'numeric' })
}
const groupedMessages = computed(() => {
  const groups: { bucket: string; items: EmailMessageListResponse[] }[] = []
  let cur = ''
  for (const m of store.messages) {
    const b = dateBucket(m.sent_at)
    if (b !== cur) { groups.push({ bucket: b, items: [] }); cur = b }
    groups[groups.length - 1].items.push(m)
  }
  return groups
})

async function onSync() {
  if (!activeAccount.value) return
  try {
    await store.syncActive()
    showToast('success', 'Sync complete')
  } catch {
    showToast('error', 'Sync failed')
  }
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => store.fetchMessages(), 300)
}

async function onClickMessage(msg: EmailMessageListResponse) {
  await store.openMessage(msg.id)
}

async function onDelete(msg: EmailMessageListResponse) {
  if (!confirm(`Delete "${msg.subject || '(no subject)'}"?`)) return
  try {
    await store.removeMessage(msg.id)
    await store.refreshCounts()
    showToast('info', 'Message deleted')
  } catch {
    showToast('error', 'Could not delete')
  }
}

async function onDownloadAttachment(attId: number, filename: string) {
  if (!store.selectedMessage) return
  try {
    await emailApi.downloadAttachment(store.selectedMessage.id, attId, filename)
  } catch {
    showToast('error', 'Download failed')
  }
}

const totalUnread = computed(() =>
  store.folders.reduce((n, f) => n + (f.unread_count || 0), 0),
)

// ── Bulk selection ──
const allSelected = computed(() =>
  store.messages.length > 0 && store.messages.every((m) => store.selectedIds.has(m.id)),
)
function toggleSelectAll() {
  if (allSelected.value) store.clearSelection()
  else store.selectAllVisible()
}
async function onBulkDelete() {
  const ids = [...store.selectedIds]
  if (!ids.length || !confirm(`Delete ${ids.length} selected message(s)?`)) return
  try {
    await store.bulkDelete(ids)
    await store.refreshCounts()
    showToast('info', `Deleted ${ids.length} message${ids.length === 1 ? '' : 's'}`)
  } catch {
    showToast('error', 'Bulk delete failed')
  }
}
async function onBulkSpam() {
  const ids = new Set(store.selectedIds)
  const targets = store.messages.filter((m) => ids.has(m.id))
  for (const m of targets) {
    try { await store.markSpam(m, true) } catch { /* keep going */ }
  }
  showToast('info', `Marked ${targets.length} as spam`)
}
async function onRescan() {
  try {
    await store.rescore()
    showToast('success', 'Rescanned mail for spam')
  } catch {
    showToast('error', 'Rescan failed')
  }
}

// ── Block-sender chooser (the Spam button on a selected message) ──
const showBlockDialog = ref(false)
const blockTarget = ref<EmailMessageListResponse | null>(null)
const blockScope = ref<'domain' | 'sender'>('domain')
const blocking = ref(false)

function openBlockChooser(msg: EmailMessageListResponse) {
  // Already spam → toggle back to not-spam (clears the blocklist entry).
  if (msg.is_spam) {
    store.markSpam(msg, false)
    return
  }
  blockTarget.value = msg
  blockScope.value = 'domain'
  showBlockDialog.value = true
}

async function confirmBlock(action: 'junk' | 'delete') {
  const target = blockTarget.value
  if (!target) return
  blocking.value = true
  try {
    const n = await store.blockSender(target, action, blockScope.value)
    showBlockDialog.value = false
    blockTarget.value = null
    showToast(
      'success',
      action === 'delete'
        ? `Blocked sender — ${n} message${n === 1 ? '' : 's'} deleted; future mail will be removed.`
        : `Blocked sender — ${n} message${n === 1 ? '' : 's'} moved to Spam; future mail hidden.`,
    )
  } catch {
    showToast('error', 'Could not block sender')
  } finally {
    blocking.value = false
  }
}
const blockScopeLabel = computed(() => {
  const m = blockTarget.value
  if (!m) return ''
  return blockScope.value === 'domain'
    ? (m.from_address.split('@')[1] || m.from_address)
    : m.from_address
})

// ── Add the current message to the Planner as a task ──
async function addToTask() {
  const m = store.selectedMessage
  if (!m) return
  const from = m.from_name ? `${m.from_name} <${m.from_address}>` : m.from_address
  const body = m.snippet || (m.text_body ? m.text_body.slice(0, 500) : '')
  try {
    await createTask({
      title: (m.subject || '(no subject)').slice(0, 200),
      notes: `From: ${from}\n\n${body}`,
    })
    showToast('success', 'Added to Tasks')
  } catch {
    showToast('error', 'Could not create task')
  }
}

// ── Realtime counts: poll folder + spam counts while the view is open ──
let pollTimer: ReturnType<typeof setInterval> | null = null
function onVisibility() {
  if (!document.hidden) store.refreshCounts()
}
onMounted(() => {
  store.init()
  pollTimer = setInterval(() => { if (!document.hidden) store.refreshCounts() }, 60000)
  document.addEventListener('visibilitychange', onVisibility)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<template>
  <div class="relative flex h-full flex-col">
    <!-- Toast -->
    <div v-if="toast" class="absolute top-3 right-4 z-50">
      <div class="flex items-center gap-2 rounded-lg px-3 py-2 text-xs shadow-lg"
        :class="{
          'bg-emerald-500/15 text-emerald-500': toast.type === 'success',
          'bg-red-500/15 text-red-500': toast.type === 'error',
          'bg-accent/15 text-accent': toast.type === 'info',
        }">
        <CheckCircle2 v-if="toast.type === 'success'" :size="14" />
        <AlertCircle v-else :size="14" />
        {{ toast.message }}
      </div>
    </div>

    <!-- ── No accounts: prompt to configure in Settings ── -->
    <div v-if="!store.loadingAccounts && !store.accounts.length" class="h-full overflow-y-auto px-6 py-10">
      <div class="mx-auto max-w-lg">
        <div class="mb-6 flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
            <Mail :size="20" class="text-accent" />
          </div>
          <div>
            <h1 class="text-lg font-semibold text-text-primary">Email</h1>
            <p class="text-xs text-text-muted">Connect a mailbox to read and send mail.</p>
          </div>
        </div>
        <div class="rounded-xl border border-border bg-surface-hover p-5">
          <p class="text-sm text-text-primary/90">No email accounts configured yet.</p>
          <p class="mt-1 text-xs leading-relaxed text-text-muted">
            Add an account in Settings. For Gmail, enable IMAP and create an App Password.
            Credentials are AES-encrypted before storage.
          </p>
          <button class="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent/90"
            @click="goToSettings">
            <Settings :size="16" /> Configure in Settings
          </button>
        </div>
      </div>
    </div>

    <!-- ── Mail client ── -->
    <template v-else-if="store.accounts.length">
      <!-- Toolbar (spans full width above the panes) -->
      <div class="flex items-center gap-1.5 border-b border-border bg-surface-hover/60 px-3 py-2">
        <button class="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90"
          @click="openCompose()">
          <Plus :size="14" /> New
        </button>
        <div class="mx-1 h-5 w-px bg-border" />
        <button class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-text-muted hover:bg-surface-hover disabled:opacity-40"
          :disabled="!store.selectedMessage" title="Reply" @click="store.selectedMessage && openCompose(store.selectedMessage, 'reply')">
          <Reply :size="14" /> Reply
        </button>
        <button class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-text-muted hover:bg-surface-hover disabled:opacity-40"
          :disabled="!store.selectedMessage" title="Reply to all" @click="store.selectedMessage && openCompose(store.selectedMessage, 'replyall')">
          <ReplyAll :size="14" /> Reply All
        </button>
        <button class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-text-muted hover:bg-surface-hover disabled:opacity-40"
          :disabled="!store.selectedMessage" title="Forward" @click="store.selectedMessage && openCompose(store.selectedMessage, 'forward')">
          <Forward :size="14" /> Forward
        </button>
        <button class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-text-muted hover:bg-surface-hover disabled:opacity-50"
          :disabled="store.syncing" @click="onSync" title="Send / Receive">
          <RefreshCw :size="14" :class="{ 'animate-spin': store.syncing }" />
        </button>
        <button class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-text-muted hover:bg-surface-hover hover:text-rose-500 disabled:opacity-40"
          :disabled="!store.selectedMessage" title="Delete" @click="store.selectedMessage && onDelete(store.selectedMessage)">
          <Trash2 :size="14" />
        </button>

        <!-- Right side: account + search -->
        <div class="ml-auto flex items-center gap-2">
          <div v-if="store.accounts.length > 1" class="relative">
            <select v-model.number="store.activeAccountId"
              class="appearance-none rounded-md border border-border bg-surface-hover py-1.5 pl-2 pr-6 text-xs text-text-primary"
              @change="store.activeAccountId && store.selectAccount(store.activeAccountId)">
              <option v-for="a in store.accounts" :key="a.id" :value="a.id">{{ a.email_address }}</option>
            </select>
            <ChevronDown :size="12" class="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-text-muted" />
          </div>
          <div class="relative w-56">
            <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
            <input v-model="store.search" placeholder="Search mail…"
              class="w-full rounded-md border border-border bg-surface-hover py-1.5 pl-8 pr-2 text-xs text-text-primary outline-none placeholder:text-text-muted"
              @input="onSearchInput" />
          </div>
          <button class="rounded-md p-1.5 text-text-muted hover:bg-surface-hover" title="Manage accounts" @click="goToSettings">
            <Settings :size="15" />
          </button>
        </div>
      </div>

      <!-- Three-pane body -->
      <div class="flex min-h-0 flex-1">
        <!-- Folder rail -->
        <aside class="flex w-52 shrink-0 flex-col border-r border-border bg-surface-hover/40">
          <!-- Account header -->
          <div class="border-b border-border px-3 py-3">
            <div class="flex items-center gap-2">
              <div class="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15 text-[12px] font-bold text-accent">
                {{ (activeAccount?.email_address || '?').charAt(0).toUpperCase() }}
              </div>
              <div class="min-w-0">
                <div class="truncate text-xs font-semibold text-text-primary">{{ activeAccount?.label }}</div>
                <div class="truncate text-[10px] text-text-muted">{{ activeAccount?.email_address }}</div>
              </div>
            </div>
          </div>

          <div class="custom-scrollbar min-h-0 flex-1 overflow-y-auto py-2">
            <!-- Virtual folders -->
            <button class="flex w-full items-center justify-between px-3 py-1.5 text-xs font-medium"
              :class="store.activeFolderId == null && !store.unreadOnly ? 'bg-accent/10 text-accent' : 'text-text-muted hover:bg-surface-hover hover:text-text-primary'"
              @click="store.selectFolder(null)">
              <span class="flex items-center gap-2"><MailOpen :size="14" /> All mail</span>
              <span v-if="store.folders.length" class="text-[10px] text-text-muted">{{ store.folders.reduce((n, f) => n + (f.message_count || 0), 0) }}</span>
            </button>
            <button class="flex w-full items-center justify-between px-3 py-1.5 text-xs font-medium"
              :class="store.unreadOnly ? 'bg-accent/10 text-accent' : 'text-text-muted hover:bg-surface-hover hover:text-text-primary'"
              @click="store.toggleUnread()">
              <span class="flex items-center gap-2"><Mail :size="14" /> Unread</span>
              <span v-if="totalUnread" class="rounded-full bg-accent px-1.5 text-[10px] font-semibold text-white">{{ totalUnread }}</span>
            </button>
            <button class="flex w-full items-center justify-between px-3 py-1.5 text-xs font-medium"
              :class="store.spamOnly ? 'bg-orange-500/15 text-orange-500' : 'text-text-muted hover:bg-surface-hover hover:text-text-primary'"
              @click="store.selectSpam()">
              <span class="flex items-center gap-2"><ShieldAlert :size="14" /> Spam</span>
              <span v-if="store.spamCount" class="rounded-full bg-orange-500/20 px-1.5 text-[10px] font-semibold text-orange-500">{{ store.spamCount }}</span>
            </button>

            <!-- Collapsible Folders section -->
            <button class="mt-2 flex w-full items-center gap-1 border-t border-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text-muted hover:text-text-primary"
              @click="foldersOpen = !foldersOpen">
              <ChevronRight :size="12" class="shrink-0 transition-transform" :class="{ 'rotate-90': foldersOpen }" />
              Folders
            </button>
            <div v-if="foldersOpen" class="pb-2">
              <template v-for="node in folderTree" :key="node.type === 'leaf' ? 'l' + node.folder.id : 'g' + node.key">
                <!-- Leaf folder -->
                <button v-if="node.type === 'leaf'"
                  class="flex w-full items-center justify-between px-3 py-1.5 text-xs"
                  :class="[
                    store.activeFolderId === node.folder.id ? 'bg-accent/10 text-accent' : 'text-text-muted hover:bg-surface-hover hover:text-text-primary',
                    node.folder.special_use ? '' : 'pl-5',
                  ]"
                  @click="store.selectFolder(node.folder.id)">
                  <span class="flex min-w-0 items-center gap-2">
                    <component :is="folderIcon(node.folder)" :size="14" class="shrink-0" :class="folderColor(node.folder)" />
                    <span class="truncate">{{ folderLabel(node.folder) }}</span>
                  </span>
                  <span v-if="node.folder.unread_count" class="ml-1 shrink-0 rounded-full bg-accent/20 px-1.5 text-[10px] font-semibold text-accent">
                    {{ node.folder.unread_count }}
                  </span>
                </button>
                <!-- Expandable group of nested folders -->
                <div v-else>
                  <button class="flex w-full items-center gap-1 px-3 py-1.5 text-xs text-text-muted hover:bg-surface-hover hover:text-text-primary"
                    @click="toggleGroup(node.key)">
                    <ChevronRight :size="12" class="shrink-0 transition-transform" :class="{ 'rotate-90': isGroupOpen(node.key) }" />
                    <FolderIcon :size="13" class="shrink-0" />
                    <span class="flex-1 truncate text-left">{{ node.label }}</span>
                    <span class="text-[10px] text-text-muted">{{ node.folders.length }}</span>
                  </button>
                  <div v-if="isGroupOpen(node.key)" class="ml-2 border-l border-border pl-1">
                    <button v-for="f in node.folders" :key="f.id"
                      class="flex w-full items-center justify-between px-2 py-1.5 text-xs"
                      :class="store.activeFolderId === f.id ? 'bg-accent/10 text-accent' : 'text-text-muted hover:bg-surface-hover hover:text-text-primary'"
                      @click="store.selectFolder(f.id)">
                      <span class="flex min-w-0 items-center gap-2">
                        <component :is="folderIcon(f)" :size="13" class="shrink-0" :class="folderColor(f)" />
                        <span class="truncate">{{ folderLabel(f) }}</span>
                      </span>
                      <span v-if="f.unread_count" class="ml-1 shrink-0 rounded-full bg-accent/20 px-1.5 text-[10px] font-semibold text-accent">
                        {{ f.unread_count }}
                      </span>
                    </button>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </aside>

        <!-- Message list (date-grouped) -->
        <section class="flex w-80 shrink-0 flex-col border-r border-border">
          <!-- Selection / bulk-action bar -->
          <div class="flex items-center gap-2 border-b border-border px-3 py-1.5">
            <button class="text-text-muted hover:text-text-primary cursor-pointer" :title="allSelected ? 'Clear selection' : 'Select all'"
              @click="toggleSelectAll">
              <CheckSquare v-if="allSelected" :size="15" class="text-accent" />
              <Square v-else :size="15" />
            </button>
            <span class="text-[11px] text-text-muted">
              {{ store.selectedIds.size ? `${store.selectedIds.size} selected` : `${store.total} message${store.total === 1 ? '' : 's'}` }}
            </span>
            <div v-if="store.selectedIds.size" class="ml-auto flex items-center gap-1">
              <button class="flex items-center gap-1 rounded-md bg-orange-500/10 px-2 py-1 text-[11px] text-orange-500 hover:bg-orange-500/20"
                @click="onBulkSpam" title="Mark selected as spam">
                <ShieldAlert :size="12" /> Spam
              </button>
              <button class="flex items-center gap-1 rounded-md bg-rose-500/10 px-2 py-1 text-[11px] text-rose-500 hover:bg-rose-500/20"
                @click="onBulkDelete" title="Delete selected">
                <Trash2 :size="12" /> Delete
              </button>
            </div>
            <button v-else-if="store.spamOnly" class="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-text-muted hover:bg-surface-hover hover:text-text-primary"
              title="Re-score all mail for spam (respects your overrides)" @click="onRescan">
              <RefreshCw :size="12" /> Rescan
            </button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto">
            <div v-if="store.loadingMessages" class="p-6 text-center text-xs text-text-muted">Loading…</div>
            <div v-else-if="!store.messages.length" class="flex h-full flex-col items-center justify-center gap-2 text-xs text-text-muted">
              <Mail :size="26" class="opacity-40" /> {{ store.spamOnly ? 'No spam flagged' : 'No messages' }}
            </div>
            <template v-else>
              <div v-for="group in groupedMessages" :key="group.bucket">
                <div class="sticky top-0 z-10 bg-surface/95 px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-text-muted backdrop-blur">
                  {{ group.bucket }}
                </div>
                <div v-for="m in group.items" :key="m.id"
                  class="flex w-full items-start gap-2 border-b border-border px-3 py-2.5 text-left transition-colors hover:bg-surface-hover"
                  :class="store.selectedMessage?.id === m.id ? 'bg-accent/5' : ''">
                  <button class="mt-0.5 shrink-0 text-text-muted hover:text-text-primary cursor-pointer"
                    :title="store.selectedIds.has(m.id) ? 'Deselect' : 'Select'" @click.stop="store.toggleSelected(m.id)">
                    <CheckSquare v-if="store.selectedIds.has(m.id)" :size="14" class="text-accent" />
                    <Square v-else :size="14" />
                  </button>
                  <button class="flex min-w-0 flex-1 items-start gap-2.5" @click="onClickMessage(m)">
                    <!-- Avatar + unread dot -->
                    <div class="relative mt-0.5 shrink-0">
                      <div class="flex h-8 w-8 items-center justify-center rounded-full text-[11px] font-bold text-white"
                        :class="avatarColor(sender(m))">
                        {{ initialsOf(sender(m)) }}
                      </div>
                      <span v-if="!m.is_read" class="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-accent ring-2 ring-surface" />
                    </div>
                    <div class="min-w-0 flex-1">
                      <div class="flex items-center justify-between gap-2">
                        <span class="truncate text-xs" :class="m.is_read ? 'font-medium text-text-muted' : 'font-semibold text-text-primary'">
                          {{ sender(m) }}
                        </span>
                        <span class="shrink-0 text-[10px] text-text-muted">{{ formatTime(m.sent_at) }}</span>
                      </div>
                      <div class="flex items-center gap-1.5">
                        <Star v-if="m.is_starred" :size="11" class="shrink-0 fill-amber-400 text-amber-400" />
                        <ShieldAlert v-if="m.is_spam" :size="11" class="shrink-0 text-orange-500" />
                        <span class="truncate text-xs" :class="m.is_read ? 'text-text-muted/80' : 'text-text-primary/90'">
                          {{ m.subject || '(no subject)' }}
                        </span>
                      </div>
                      <div class="flex items-center gap-1.5">
                        <Paperclip v-if="m.has_attachments" :size="10" class="shrink-0 text-text-muted" />
                        <span class="truncate text-[11px] text-text-muted">{{ m.snippet }}</span>
                      </div>
                    </div>
                  </button>
                </div>
              </div>
              <!-- Load more -->
              <div class="p-3 text-center">
                <button v-if="store.hasMore"
                  class="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-[11px] text-text-muted hover:bg-surface-hover hover:text-text-primary disabled:opacity-50"
                  :disabled="store.loadingMore" @click="store.loadMore()">
                  <RefreshCw v-if="store.loadingMore" :size="12" class="animate-spin" />
                  {{ store.loadingMore ? 'Loading…' : `Load more (${store.total - store.messages.length} left)` }}
                </button>
                <span v-else class="text-[10px] text-text-muted">End of list</span>
              </div>
            </template>
          </div>
        </section>

        <!-- Reader -->
        <section class="flex min-w-0 flex-1 flex-col">
          <div v-if="store.loadingDetail" class="p-6 text-center text-xs text-text-muted">Loading…</div>
          <div v-else-if="!store.selectedMessage" class="flex h-full items-center justify-center text-xs text-text-muted">
            <div class="flex flex-col items-center gap-2">
              <Mail :size="28" class="opacity-40" /> Select a message to read
            </div>
          </div>
          <template v-else>
            <!-- Scrollable head + body -->
            <div class="min-h-0 flex-1 overflow-y-auto">
              <article class="flex flex-col gap-3 p-5">
                <div class="flex items-start justify-between gap-3">
                  <h2 class="text-base font-semibold text-text-primary">{{ store.selectedMessage.subject || '(no subject)' }}</h2>
                  <div class="flex shrink-0 items-center gap-0.5">
                    <button class="rounded p-1.5 text-text-muted hover:bg-surface-hover hover:text-accent" title="Add to Tasks"
                      @click="addToTask">
                      <ListTodo :size="15" />
                    </button>
                    <button class="rounded p-1.5 hover:bg-surface-hover"
                      :class="store.selectedMessage.is_spam ? 'text-orange-500' : 'text-text-muted'"
                      :title="store.selectedMessage.is_spam ? 'Not spam' : 'Block sender (move to Junk / delete)'"
                      @click="openBlockChooser(store.selectedMessage)">
                      <ShieldAlert :size="15" />
                    </button>
                    <button class="rounded p-1.5 text-text-muted hover:bg-surface-hover" :title="store.selectedMessage.is_starred ? 'Unstar' : 'Star'"
                      @click="store.toggleStar(store.selectedMessage)">
                      <Star :size="15" :class="{ 'fill-amber-400 text-amber-400': store.selectedMessage.is_starred }" />
                    </button>
                    <button class="rounded p-1.5 text-text-muted hover:bg-surface-hover" :title="store.selectedMessage.is_read ? 'Mark unread' : 'Mark read'"
                      @click="store.toggleRead(store.selectedMessage)">
                      <MailOpen :size="15" />
                    </button>
                    <button class="rounded p-1.5 text-text-muted hover:bg-surface-hover hover:text-rose-500" title="Delete"
                      @click="onDelete(store.selectedMessage)">
                      <Trash2 :size="15" />
                    </button>
                  </div>
                </div>

                <div class="flex items-start gap-3 border-b border-border pb-3">
                  <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[12px] font-bold text-white"
                    :class="avatarColor(store.selectedMessage.from_name || store.selectedMessage.from_address)">
                    {{ initialsOf(store.selectedMessage.from_name || store.selectedMessage.from_address) }}
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center justify-between gap-2">
                      <span class="truncate text-sm font-semibold text-text-primary">
                        {{ store.selectedMessage.from_name || store.selectedMessage.from_address }}
                      </span>
                      <span class="shrink-0 text-[11px] text-text-muted">{{ formatFullDate(store.selectedMessage.sent_at) }}</span>
                    </div>
                    <div class="text-[11px] text-text-muted">
                      <span class="text-text-muted/70">From:</span> {{ store.selectedMessage.from_address }}
                    </div>
                    <div class="text-[11px] text-text-muted">
                      <span class="text-text-muted/70">To:</span> {{ store.selectedMessage.to_addresses.map((t) => t.address).join(', ') }}
                    </div>
                  </div>
                </div>

                <!-- Body: prefer plain text; fall back to sandboxed HTML -->
                <pre v-if="store.selectedMessage.text_body"
                  class="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-text-primary/90">{{ store.selectedMessage.text_body }}</pre>
                <iframe v-else-if="store.selectedMessage.html_body"
                  :srcdoc="store.selectedMessage.html_body" sandbox=""
                  class="h-[55vh] w-full rounded-md border border-border" />

                <!-- Attachments -->
                <div v-if="store.selectedMessage.attachments.length" class="flex flex-wrap gap-2 pt-1">
                  <button v-for="att in store.selectedMessage.attachments" :key="att.id"
                    class="flex items-center gap-1.5 rounded-md border border-border bg-surface-hover px-2.5 py-1.5 text-xs text-text-muted hover:bg-surface-hover"
                    @click="onDownloadAttachment(att.id, att.filename)">
                    <Paperclip :size="12" />
                    <span class="max-w-[160px] truncate">{{ att.filename }}</span>
                    <span class="text-[10px] text-text-muted/70">{{ formatSize(att.file_size) }}</span>
                    <Download :size="12" />
                  </button>
                </div>
              </article>
            </div>

            <!-- Quick reply bar -->
            <div class="shrink-0 border-t border-border bg-surface-hover/50 p-3">
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[11px] font-medium text-text-muted">
                  Reply to {{ store.selectedMessage.from_name || store.selectedMessage.from_address }}
                </span>
                <button class="text-[10px] text-text-muted hover:text-text-primary" @click="openCompose(store.selectedMessage, 'reply')">
                  Full compose →
                </button>
              </div>
              <textarea v-model="quickReply" rows="2"
                placeholder="Type your Quick Reply here and use Ctrl+Enter to send it…"
                class="w-full resize-none rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs leading-relaxed text-text-primary outline-none placeholder:text-text-muted focus:border-accent"
                @keydown="onQuickReplyKeydown" />
              <div class="mt-1.5 flex items-center justify-end gap-2">
                <button class="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1 text-[11px] font-medium text-white hover:bg-accent/90 disabled:opacity-50"
                  :disabled="sending || !quickReply.trim()" @click="sendQuickReply">
                  <Send :size="12" /> {{ sending ? 'Sending…' : 'Send' }}
                </button>
              </div>
            </div>
          </template>
        </section>
      </div>
    </template>

    <!-- ── Compose modal ── -->
    <Teleport to="body">
    <div v-if="showCompose" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="showCompose = false">
      <div class="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-xl">
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-border px-4 py-2.5">
          <div class="flex items-center gap-2">
            <h3 class="text-sm font-semibold text-text-primary">New message</h3>
            <span v-if="activeAccount" class="rounded bg-surface-hover px-1.5 py-0.5 text-[10px] text-text-muted">
              from {{ activeAccount.email_address }}
            </span>
          </div>
          <button class="text-text-muted hover:text-text-primary" @click="showCompose = false"><X :size="16" /></button>
        </div>

        <!-- Body -->
        <div class="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-4">
          <!-- Recipients -->
          <div class="flex items-center gap-2">
            <label class="w-10 shrink-0 text-[11px] font-medium text-text-muted">To</label>
            <input ref="composeToRef" v-model="compose.to" placeholder="recipient@example.com (comma-separated)"
              class="flex-1 rounded-md border border-border bg-surface-hover px-2.5 py-1.5 text-sm text-text-primary outline-none focus:border-accent" />
            <button class="shrink-0 rounded-md px-2 py-1 text-[11px] text-text-muted hover:bg-surface-hover hover:text-text-primary"
              :class="{ 'bg-surface-hover text-text-primary': showCc }" @click="showCc = !showCc">
              Cc
            </button>
          </div>
          <div v-if="showCc" class="flex items-center gap-2">
            <label class="w-10 shrink-0 text-[11px] font-medium text-text-muted">Cc</label>
            <input v-model="compose.cc" placeholder="cc@example.com (comma-separated)"
              class="flex-1 rounded-md border border-border bg-surface-hover px-2.5 py-1.5 text-sm text-text-primary outline-none focus:border-accent" />
          </div>
          <!-- Subject -->
          <div class="flex items-center gap-2">
            <label class="w-10 shrink-0 text-[11px] font-medium text-text-muted">Subject</label>
            <input v-model="compose.subject" placeholder="Subject"
              class="flex-1 rounded-md border border-border bg-surface-hover px-2.5 py-1.5 text-sm text-text-primary outline-none focus:border-accent" />
          </div>
          <!-- Body -->
          <textarea v-model="compose.body" rows="9" placeholder="Write your message…"
            class="min-h-[180px] flex-1 resize-none rounded-md border border-border bg-surface-hover px-2.5 py-1.5 text-sm leading-relaxed text-text-primary outline-none focus:border-accent" />
          <!-- Attachments -->
          <div v-if="compose.attachments.length" class="flex flex-wrap gap-2">
            <span v-for="a in compose.attachments" :key="a.id"
              class="flex items-center gap-1.5 rounded-md border border-border bg-surface-hover py-1 pl-2 pr-1 text-xs text-text-muted">
              <Paperclip :size="11" />
              <span class="max-w-[180px] truncate">{{ a.filename }}</span>
              <button class="rounded p-0.5 text-text-muted hover:bg-surface-hover hover:text-rose-500" title="Remove" @click="removeAttachment(a.id)">
                <X :size="11" />
              </button>
            </span>
          </div>
        </div>

        <!-- Footer -->
        <div class="flex items-center gap-2 border-t border-border px-4 py-2.5">
          <button class="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-text-muted hover:bg-surface-hover"
            @click="attachInput?.click()">
            <Paperclip :size="13" /> Attach
          </button>
          <input ref="attachInput" type="file" multiple class="hidden" @change="onAttachFiles" />
          <div class="ml-auto flex items-center gap-2">
            <button class="rounded-md border border-border px-3 py-1.5 text-xs text-text-muted hover:bg-surface-hover disabled:opacity-50"
              :disabled="sending" @click="sendCompose(true)">Save draft</button>
            <button class="flex items-center gap-1.5 rounded-md bg-accent px-4 py-1.5 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-50"
              :disabled="sending" @click="sendCompose(false)">
              <Send :size="13" /> {{ sending ? 'Sending…' : 'Send' }}
            </button>
          </div>
        </div>
      </div>
    </div>
    </Teleport>

    <!-- ── Block-sender chooser ── -->
    <Teleport to="body">
    <div v-if="showBlockDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="!blocking && (showBlockDialog = false)">
      <div class="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-xl">
        <div class="flex items-center gap-2 border-b border-border px-4 py-3">
          <ShieldAlert :size="16" class="text-orange-500" />
          <h3 class="text-sm font-semibold text-text-primary">Block sender</h3>
          <button class="ml-auto text-text-muted hover:text-text-primary" :disabled="blocking" @click="showBlockDialog = false">
            <X :size="16" />
          </button>
        </div>
        <div class="max-h-[80vh] space-y-3 overflow-y-auto p-4">
          <p class="text-xs text-text-muted">
            Block <span class="font-medium text-text-primary">{{ blockTarget?.from_name || blockTarget?.from_address }}</span>.
            This applies to <span class="text-text-primary">existing and future mail</span> from them.
          </p>

          <!-- Scope toggle -->
          <div class="flex gap-2">
            <button class="flex flex-1 items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs"
              :class="blockScope === 'domain' ? 'border-accent bg-accent/10 text-accent' : 'border-border text-text-muted hover:bg-surface-hover'"
              @click="blockScope = 'domain'">
              <Globe :size="12" /> Whole domain
            </button>
            <button class="flex flex-1 items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs"
              :class="blockScope === 'sender' ? 'border-accent bg-accent/10 text-accent' : 'border-border text-text-muted hover:bg-surface-hover'"
              @click="blockScope = 'sender'">
              <User :size="12" /> This address only
            </button>
          </div>
          <p class="text-[10px] text-text-muted">
            Blocking: <span class="font-mono">{{ blockScopeLabel }}</span>
          </p>

          <!-- Action buttons -->
          <div class="flex gap-2 pt-1">
            <button class="flex flex-1 flex-col items-center gap-0.5 rounded-md border border-orange-500/40 bg-orange-500/10 px-3 py-2 text-orange-600 hover:bg-orange-500/20 disabled:opacity-50 dark:text-orange-400"
              :disabled="blocking" @click="confirmBlock('junk')">
              <Ban :size="15" />
              <span class="text-xs font-medium">Move to Junk</span>
              <span class="text-[10px] opacity-80">Hide in Spam folder</span>
            </button>
            <button class="flex flex-1 flex-col items-center gap-0.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-rose-600 hover:bg-rose-500/20 disabled:opacity-50 dark:text-rose-400"
              :disabled="blocking" @click="confirmBlock('delete')">
              <Trash2 :size="15" />
              <span class="text-xs font-medium">Delete</span>
              <span class="text-[10px] opacity-80">Remove existing + future</span>
            </button>
          </div>
        </div>
      </div>
    </div>
    </Teleport>
  </div>
</template>
