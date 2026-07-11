<script setup lang="ts">
/**
 * EmailView — IMAP/SMTP mail client.
 *
 * Three-pane layout (folders | message list | reader) once at least one
 * account is configured; otherwise an account-setup card. Composing opens a
 * modal. HTML message bodies are rendered in a sandboxed iframe so external
 * styles/scripts can't affect the app.
 */
import { computed, onMounted, ref } from 'vue'
import { useEmailStore } from '../../stores/email'
import * as emailApi from '../../api/email'
import type {
  EmailAccountCreate,
  EmailFolderResponse,
  EmailMessageListResponse,
  TempAttachmentResponse,
} from '../../types'
import {
  Mail, Inbox, Send, Star, Trash2, RefreshCw, Plus, Pencil, X, Search,
  Reply, Paperclip, Download, AlertCircle, CheckCircle2, Folder as FolderIcon,
  Archive, Ban, FileEdit, MailOpen,
} from 'lucide-vue-next'

const store = useEmailStore()

// ── Toast ──
const toast = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error' | 'info', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3500)
}

// ── Account modal ──
const showAccountForm = ref(false)
const editingAccount = ref<number | null>(null)
const accountForm = ref<EmailAccountCreate>(emptyAccountForm())
const testing = ref(false)

function emptyAccountForm(): EmailAccountCreate {
  return {
    label: '', email_address: '',
    imap_host: '', imap_port: 993, imap_use_ssl: true,
    smtp_host: '', smtp_port: 587, smtp_use_tls: true,
    username: '', password: '', display_name: '', poll_interval_minutes: 10,
  }
}

function openCreateAccount() {
  editingAccount.value = null
  accountForm.value = emptyAccountForm()
  showAccountForm.value = true
}
function openEditAccount() {
  const a = activeAccount.value
  if (!a) return
  editingAccount.value = a.id
  accountForm.value = {
    label: a.label, email_address: a.email_address,
    imap_host: a.imap_host, imap_port: a.imap_port, imap_use_ssl: a.imap_use_ssl,
    smtp_host: a.smtp_host, smtp_port: a.smtp_port, smtp_use_tls: a.smtp_use_tls,
    username: a.username, password: '', display_name: a.display_name ?? '',
    poll_interval_minutes: a.poll_interval_minutes,
  }
  showAccountForm.value = true
}

async function submitAccount() {
  try {
    if (editingAccount.value != null) {
      const updates: Record<string, unknown> = { ...accountForm.value }
      if (!updates.password) delete updates.password // leave password unchanged
      await emailApi.updateAccount(editingAccount.value, updates)
      showToast('success', 'Account updated')
    } else {
      await emailApi.createAccount(accountForm.value)
      showToast('success', 'Account added — syncing folders')
    }
    showAccountForm.value = false
    await store.fetchAccounts()
  } catch (e) {
    showToast('error', e instanceof Error ? e.message : 'Could not save account')
  }
}

async function testAccount() {
  // Save first if editing/creating so the server can connect with stored creds.
  testing.value = true
  try {
    let id = editingAccount.value
    if (id == null) {
      const created = await emailApi.createAccount(accountForm.value)
      id = created.id
      editingAccount.value = id
      await store.fetchAccounts()
    }
    const res = await emailApi.testAccount(id!)
    showToast(res.success ? 'success' : 'error', res.success ? 'Connection OK' : `Failed: ${res.error}`)
  } catch (e) {
    showToast('error', e instanceof Error ? e.message : 'Test failed')
  } finally {
    testing.value = false
  }
}

async function removeAccount() {
  const a = activeAccount.value
  if (!a || !confirm(`Remove account "${a.label}" and all its cached messages?`)) return
  try {
    await emailApi.deleteAccount(a.id)
    showToast('info', 'Account removed')
    store.activeAccountId = null
    await store.fetchAccounts()
  } catch {
    showToast('error', 'Could not remove account')
  }
}

// ── Compose modal ──
const showCompose = ref(false)
const compose = ref({
  to: '', cc: '', subject: '', body: '',
  in_reply_to_message_id: null as number | null,
  attachments: [] as TempAttachmentResponse[],
})
const sending = ref(false)
const attachInput = ref<HTMLInputElement | null>(null)

function openCompose(replyTo?: EmailMessageListResponse) {
  compose.value = { to: '', cc: '', subject: '', body: '', in_reply_to_message_id: null, attachments: [] }
  if (replyTo) {
    compose.value.to = replyTo.from_address
    compose.value.subject = replyTo.subject?.startsWith('Re:') ? replyTo.subject : `Re: ${replyTo.subject ?? ''}`
    compose.value.in_reply_to_message_id = replyTo.id
  }
  showCompose.value = true
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

// ── Folder / message helpers ──
const activeAccount = computed(() => store.accounts.find((a) => a.id === store.activeAccountId) ?? null)

const FOLDER_META: Record<string, { icon: typeof Inbox; label: string }> = {
  inbox: { icon: Inbox, label: 'Inbox' },
  sent: { icon: Send, label: 'Sent' },
  drafts: { icon: FileEdit, label: 'Drafts' },
  trash: { icon: Trash2, label: 'Trash' },
  junk: { icon: Ban, label: 'Junk' },
  archive: { icon: Archive, label: 'Archive' },
}
function folderIcon(f: EmailFolderResponse) {
  return (f.special_use && FOLDER_META[f.special_use]?.icon) || FolderIcon
}
function folderLabel(f: EmailFolderResponse) {
  return (f.special_use && FOLDER_META[f.special_use]?.label) || f.display_name || f.folder_name
}

function sender(msg: EmailMessageListResponse) {
  return msg.from_name || msg.from_address
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
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

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

onMounted(() => store.init())
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

    <!-- ── No accounts: setup card ── -->
    <div v-if="!store.loadingAccounts && !store.accounts.length" class="h-full overflow-y-auto px-6 py-10">
      <div class="mx-auto max-w-lg">
        <div class="mb-6 flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
            <Mail :size="20" class="text-accent" />
          </div>
          <div>
            <h1 class="text-lg font-semibold text-foreground">Email</h1>
            <p class="text-xs text-muted-foreground">Connect a mailbox to read and send mail.</p>
          </div>
        </div>
        <div class="rounded-xl border border-border bg-card p-5">
          <button class="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-accent-foreground hover:bg-accent/90"
            @click="openCreateAccount">
            <Plus :size="16" /> Add email account
          </button>
          <p class="mt-4 text-xs leading-relaxed text-muted-foreground">
            Use an app-specific password. For Gmail, enable IMAP and create an App Password.
            Credentials are AES-encrypted before storage.
          </p>
        </div>
      </div>
    </div>

    <!-- ── Mail client ── -->
    <template v-else-if="store.accounts.length">
      <!-- Header -->
      <div class="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-lg bg-accent/10 flex items-center justify-center">
            <Mail :size="18" class="text-accent" />
          </div>
          <div class="flex flex-col">
            <select v-if="store.accounts.length > 1"
              v-model.number="store.activeAccountId"
              class="rounded-md border border-border bg-card px-2 py-1 text-sm text-foreground"
              @change="store.activeAccountId && store.selectAccount(store.activeAccountId)">
              <option v-for="a in store.accounts" :key="a.id" :value="a.id">{{ a.label }}</option>
            </select>
            <span v-else class="text-sm font-semibold text-foreground">{{ activeAccount?.label }}</span>
            <span class="text-[11px] text-muted-foreground">{{ activeAccount?.email_address }}</span>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button class="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
            :disabled="store.syncing" @click="onSync">
            <RefreshCw :size="13" :class="{ 'animate-spin': store.syncing }" /> Sync
          </button>
          <button class="flex items-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted"
            title="Account settings" @click="openEditAccount">
            <Pencil :size="13" />
          </button>
          <button class="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground hover:bg-accent/90"
            @click="openCompose()">
            <Plus :size="14" /> Compose
          </button>
        </div>
      </div>

      <!-- Three-pane body -->
      <div class="flex min-h-0 flex-1">
        <!-- Folder rail -->
        <aside class="w-48 shrink-0 overflow-y-auto border-r border-border bg-card/40 py-2">
          <button class="flex w-full items-center justify-between px-3 py-1.5 text-xs font-medium"
            :class="store.activeFolderId == null ? 'text-accent' : 'text-muted-foreground hover:text-foreground'"
            @click="store.selectFolder(null)">
            <span class="flex items-center gap-2"><MailOpen :size="14" /> All mail</span>
          </button>
          <button class="flex w-full items-center justify-between px-3 py-1.5 text-xs font-medium"
            :class="store.unreadOnly ? 'text-accent' : 'text-muted-foreground hover:text-foreground'"
            @click="store.unreadOnly = !store.unreadOnly; store.fetchMessages()">
            <span class="flex items-center gap-2"><Star :size="14" /> Unread</span>
          </button>
          <div class="my-2 border-t border-border" />
          <button v-for="f in store.folders" :key="f.id"
            class="flex w-full items-center justify-between px-3 py-1.5 text-xs"
            :class="store.activeFolderId === f.id ? 'bg-accent/10 text-accent' : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
            @click="store.selectFolder(f.id)">
            <span class="flex min-w-0 items-center gap-2">
              <component :is="folderIcon(f)" :size="14" class="shrink-0" />
              <span class="truncate">{{ folderLabel(f) }}</span>
            </span>
            <span v-if="f.unread_count" class="ml-1 shrink-0 rounded-full bg-accent/20 px-1.5 text-[10px] font-semibold text-accent">
              {{ f.unread_count }}
            </span>
          </button>
        </aside>

        <!-- Message list -->
        <section class="flex w-72 shrink-0 flex-col border-r border-border">
          <div class="border-b border-border p-2">
            <div class="flex items-center gap-2 rounded-md bg-muted px-2 py-1.5">
              <Search :size="13" class="text-muted-foreground" />
              <input v-model="store.search" placeholder="Search mail…"
                class="w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
                @input="onSearchInput" />
            </div>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto">
            <div v-if="store.loadingMessages" class="p-4 text-center text-xs text-muted-foreground">Loading…</div>
            <div v-else-if="!store.messages.length" class="p-4 text-center text-xs text-muted-foreground">No messages</div>
            <button v-for="m in store.messages" :key="m.id"
              class="flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left transition-colors hover:bg-muted"
              :class="store.selectedMessage?.id === m.id ? 'bg-accent/5' : ''"
              @click="onClickMessage(m)">
              <div class="flex items-center justify-between gap-2">
                <span class="truncate text-xs font-semibold" :class="m.is_read ? 'text-muted-foreground' : 'text-foreground'">
                  {{ sender(m) }}
                </span>
                <span class="shrink-0 text-[10px] text-muted-foreground">{{ formatTime(m.sent_at) }}</span>
              </div>
              <span class="truncate text-xs" :class="m.is_read ? 'text-muted-foreground' : 'text-foreground/90'">
                {{ m.subject || '(no subject)' }}
              </span>
              <div class="flex items-center gap-1.5">
                <Star v-if="m.is_starred" :size="11" class="shrink-0 text-amber-400" />
                <Paperclip v-if="m.has_attachments" :size="11" class="shrink-0 text-muted-foreground" />
                <span class="truncate text-[11px] text-muted-foreground">{{ m.snippet }}</span>
              </div>
            </button>
          </div>
        </section>

        <!-- Reader -->
        <section class="min-w-0 flex-1 overflow-y-auto">
          <div v-if="store.loadingDetail" class="p-6 text-center text-xs text-muted-foreground">Loading…</div>
          <div v-else-if="!store.selectedMessage" class="flex h-full items-center justify-center text-xs text-muted-foreground">
            <div class="flex flex-col items-center gap-2">
              <Mail :size="28" class="opacity-40" />
              Select a message to read
            </div>
          </div>
          <article v-else class="flex flex-col gap-3 p-5">
            <div class="flex items-start justify-between gap-3">
              <h2 class="text-base font-semibold text-foreground">{{ store.selectedMessage.subject || '(no subject)' }}</h2>
              <div class="flex shrink-0 items-center gap-1">
                <button class="rounded p-1.5 text-muted-foreground hover:bg-muted" :title="store.selectedMessage.is_starred ? 'Unstar' : 'Star'"
                  @click="store.toggleStar(store.selectedMessage)">
                  <Star :size="15" :class="{ 'fill-amber-400 text-amber-400': store.selectedMessage.is_starred }" />
                </button>
                <button class="rounded p-1.5 text-muted-foreground hover:bg-muted" :title="store.selectedMessage.is_read ? 'Mark unread' : 'Mark read'"
                  @click="store.toggleRead(store.selectedMessage)">
                  <MailOpen :size="15" />
                </button>
                <button class="rounded p-1.5 text-muted-foreground hover:bg-muted" title="Delete"
                  @click="onDelete(store.selectedMessage)">
                  <Trash2 :size="15" />
                </button>
              </div>
            </div>
            <div class="flex items-center justify-between border-b border-border pb-3">
              <div class="min-w-0">
                <div class="text-xs font-medium text-foreground">
                  {{ store.selectedMessage.from_name || store.selectedMessage.from_address }}
                </div>
                <div class="text-[11px] text-muted-foreground">
                  {{ store.selectedMessage.from_address }} → {{ store.selectedMessage.to_addresses.map((t) => t.address).join(', ') }}
                </div>
              </div>
              <span class="shrink-0 text-[11px] text-muted-foreground">{{ formatTime(store.selectedMessage.sent_at) }}</span>
            </div>

            <!-- Body: prefer plain text; fall back to sandboxed HTML -->
            <pre v-if="store.selectedMessage.text_body"
              class="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-foreground/90">{{ store.selectedMessage.text_body }}</pre>
            <iframe v-else-if="store.selectedMessage.html_body"
              :srcdoc="store.selectedMessage.html_body" sandbox=""
              class="h-[60vh] w-full rounded-md border border-border" />

            <!-- Attachments -->
            <div v-if="store.selectedMessage.attachments.length" class="flex flex-wrap gap-2 pt-2">
              <button v-for="att in store.selectedMessage.attachments" :key="att.id"
                class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted"
                @click="onDownloadAttachment(att.id, att.filename)">
                <Paperclip :size="12" />
                <span class="max-w-[160px] truncate">{{ att.filename }}</span>
                <span class="text-[10px] text-muted-foreground/70">{{ formatSize(att.file_size) }}</span>
                <Download :size="12" />
              </button>
            </div>

            <div class="pt-2">
              <button class="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted"
                @click="openCompose(store.selectedMessage)">
                <Reply :size="13" /> Reply
              </button>
            </div>
          </article>
        </section>
      </div>
    </template>

    <!-- ── Account modal ── -->
    <div v-if="showAccountForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="showAccountForm = false">
      <div class="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-background p-5 shadow-xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-foreground">
            {{ editingAccount != null ? 'Edit account' : 'Add email account' }}
          </h3>
          <button class="text-muted-foreground hover:text-foreground" @click="showAccountForm = false"><X :size="16" /></button>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <label class="col-span-2 flex flex-col gap-1 text-xs text-muted-foreground">
            Label
            <input v-model="accountForm.label" placeholder="Work" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <label class="col-span-2 flex flex-col gap-1 text-xs text-muted-foreground">
            Email address
            <input v-model="accountForm.email_address" type="email" placeholder="you@example.com" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            IMAP host
            <input v-model="accountForm.imap_host" placeholder="imap.example.com" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            IMAP port
            <input v-model.number="accountForm.imap_port" type="number" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            SMTP host
            <input v-model="accountForm.smtp_host" placeholder="smtp.example.com" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            SMTP port
            <input v-model.number="accountForm.smtp_port" type="number" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            Username
            <input v-model="accountForm.username" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-xs text-muted-foreground">
            Password {{ editingAccount != null ? '(leave blank to keep)' : '' }}
            <input v-model="accountForm.password" type="password" autocomplete="new-password" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <label class="col-span-2 flex flex-col gap-1 text-xs text-muted-foreground">
            Display name (optional)
            <input v-model="accountForm.display_name" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          </label>
          <div class="col-span-2 flex items-center gap-4 text-xs text-muted-foreground">
            <label class="flex items-center gap-1.5"><input v-model="accountForm.imap_use_ssl" type="checkbox" /> IMAP SSL</label>
            <label class="flex items-center gap-1.5"><input v-model="accountForm.smtp_use_tls" type="checkbox" /> SMTP TLS</label>
          </div>
        </div>
        <div class="mt-5 flex items-center justify-between gap-2">
          <button class="text-xs text-red-500 hover:underline" v-if="editingAccount != null" @click="removeAccount">Remove account</button>
          <div v-else />
          <div class="flex items-center gap-2">
            <button class="rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
              :disabled="testing" @click="testAccount">Test connection</button>
            <button class="rounded-md bg-accent px-4 py-1.5 text-xs font-medium text-accent-foreground hover:bg-accent/90"
              @click="submitAccount">{{ editingAccount != null ? 'Save' : 'Add account' }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Compose modal ── -->
    <div v-if="showCompose" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="showCompose = false">
      <div class="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl border border-border bg-background shadow-xl">
        <div class="flex items-center justify-between border-b border-border px-4 py-2.5">
          <h3 class="text-sm font-semibold text-foreground">New message</h3>
          <button class="text-muted-foreground hover:text-foreground" @click="showCompose = false"><X :size="16" /></button>
        </div>
        <div class="flex flex-col gap-2 overflow-y-auto p-4">
          <input v-model="compose.to" placeholder="To (comma-separated)" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          <input v-model="compose.cc" placeholder="Cc (comma-separated)" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          <input v-model="compose.subject" placeholder="Subject" class="rounded-md border border-border bg-card px-2.5 py-1.5 text-sm text-foreground outline-none" />
          <textarea v-model="compose.body" rows="9" placeholder="Write your message…"
            class="resize-none rounded-md border border-border bg-card px-2.5 py-1.5 text-sm leading-relaxed text-foreground outline-none" />
          <div v-if="compose.attachments.length" class="flex flex-wrap gap-2">
            <span v-for="a in compose.attachments" :key="a.id"
              class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs text-muted-foreground">
              <Paperclip :size="11" /> {{ a.filename }}
            </span>
          </div>
          <div class="flex items-center gap-2">
            <button class="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted"
              @click="attachInput?.click()">
              <Paperclip :size="13" /> Attach
            </button>
            <input ref="attachInput" type="file" multiple class="hidden" @change="onAttachFiles" />
          </div>
        </div>
        <div class="flex items-center justify-end gap-2 border-t border-border px-4 py-2.5">
          <button class="rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
            :disabled="sending" @click="sendCompose(true)">Save draft</button>
          <button class="flex items-center gap-1.5 rounded-md bg-accent px-4 py-1.5 text-xs font-medium text-accent-foreground hover:bg-accent/90 disabled:opacity-50"
            :disabled="sending" @click="sendCompose(false)">
            <Send :size="13" /> {{ sending ? 'Sending…' : 'Send' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
