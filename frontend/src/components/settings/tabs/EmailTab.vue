<script setup lang="ts">
/**
 * EmailTab — email account configuration (moved here from EmailView).
 *
 * The form is built around a **provider** preset (Gmail, Outlook, …) that
 * auto-fills IMAP/SMTP host/port/security, so the user usually only picks a
 * provider, types their address, user ID, and password. "Other / Custom"
 * reveals the advanced server fields. Provider is a UI-only affordance — the
 * stored config is still the concrete host/port values.
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { errMsg } from '../../../utils/error'
import { useEmailStore } from '../../../stores/email'
import * as emailApi from '../../../api/email'
import type { EmailAccountResponse, EmailAccountCreate, EmailAccountUpdate } from '../../../types'
import {
  Mail, Plus, Pencil, Trash2, PlugZap, Check, X, Server, AlertTriangle,
  CheckCircle2, Loader,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SettingRow from '../shared/SettingRow.vue'
import AccordionItem from '../shared/AccordionItem.vue'
import SButton from '../shared/SButton.vue'

const emit = defineEmits<{ toast: [type: 'success' | 'error' | 'info', message: string] }>()

const store = useEmailStore()

// ── Provider presets (UI-only; map to concrete host/port) ──
interface ProviderPreset {
  id: string
  label: string
  imap_host: string
  imap_port: number
  imap_use_ssl: boolean
  smtp_host: string
  smtp_port: number
  smtp_use_tls: boolean
  hint?: string
}
const PROVIDERS: ProviderPreset[] = [
  { id: 'gmail', label: 'Gmail', imap_host: 'imap.gmail.com', imap_port: 993, imap_use_ssl: true, smtp_host: 'smtp.gmail.com', smtp_port: 587, smtp_use_tls: true, hint: 'Enable IMAP and use a Gmail App Password (2FA required).' },
  { id: 'outlook', label: 'Outlook / Microsoft 365', imap_host: 'outlook.office365.com', imap_port: 993, imap_use_ssl: true, smtp_host: 'smtp.office365.com', smtp_port: 587, smtp_use_tls: true },
  { id: 'yahoo', label: 'Yahoo', imap_host: 'imap.mail.yahoo.com', imap_port: 993, imap_use_ssl: true, smtp_host: 'smtp.mail.yahoo.com', smtp_port: 587, smtp_use_tls: true, hint: 'Use a Yahoo app password.' },
  { id: 'icloud', label: 'iCloud', imap_host: 'imap.mail.me.com', imap_port: 993, imap_use_ssl: true, smtp_host: 'smtp.mail.me.com', smtp_port: 587, smtp_use_tls: true, hint: 'Use an app-specific password.' },
  { id: 'zoho', label: 'Zoho', imap_host: 'imap.zoho.com', imap_port: 993, imap_use_ssl: true, smtp_host: 'smtp.zoho.com', smtp_port: 587, smtp_use_tls: true },
  { id: 'fastmail', label: 'Fastmail', imap_host: 'imap.fastmail.com', imap_port: 993, imap_use_ssl: true, smtp_host: 'smtp.fastmail.com', smtp_port: 587, smtp_use_tls: true },
  { id: 'proton', label: 'Proton Mail (Bridge)', imap_host: '127.0.0.1', imap_port: 1143, imap_use_ssl: false, smtp_host: '127.0.0.1', smtp_port: 1025, smtp_use_tls: false, hint: 'Requires Proton Mail Bridge running locally.' },
  { id: 'other', label: 'Other / Custom', imap_host: '', imap_port: 993, imap_use_ssl: true, smtp_host: '', smtp_port: 587, smtp_use_tls: true, hint: 'Enter your IMAP and SMTP server details below.' },
]
const PROVIDER_BY_ID = Object.fromEntries(PROVIDERS.map((p) => [p.id, p]))
const isCustom = computed(() => form.provider === 'other')

function detectProvider(imapHost: string): string {
  const h = (imapHost || '').toLowerCase()
  const match = PROVIDERS.find((p) => p.id !== 'other' && p.imap_host && p.imap_host === h)
  return match?.id ?? 'other'
}
function providerLabel(a: EmailAccountResponse): string {
  return PROVIDER_BY_ID[detectProvider(a.imap_host)]?.label ?? 'Custom'
}

// ── Form state ──
const showForm = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const testing = ref(false)

function blankForm() {
  return {
    provider: 'gmail',
    label: '',
    email_address: '',
    username: '',
    password: '',
    display_name: '',
    imap_host: PROVIDER_BY_ID.gmail.imap_host,
    imap_port: PROVIDER_BY_ID.gmail.imap_port,
    imap_use_ssl: PROVIDER_BY_ID.gmail.imap_use_ssl,
    smtp_host: PROVIDER_BY_ID.gmail.smtp_host,
    smtp_port: PROVIDER_BY_ID.gmail.smtp_port,
    smtp_use_tls: PROVIDER_BY_ID.gmail.smtp_use_tls,
    poll_interval_minutes: 10,
  }
}
const form = reactive(blankForm())

function applyProvider(id: string) {
  const p = PROVIDER_BY_ID[id]
  if (!p) return
  form.imap_host = p.imap_host
  form.imap_port = p.imap_port
  form.imap_use_ssl = p.imap_use_ssl
  form.smtp_host = p.smtp_host
  form.smtp_port = p.smtp_port
  form.smtp_use_tls = p.smtp_use_tls
}

const presetHint = computed(() => PROVIDER_BY_ID[form.provider]?.hint)

const isEdit = computed(() => editingId.value !== null)
/** Password is required to create; on edit it may stay blank (keep current). */
const canSave = computed(() =>
  !!form.provider &&
  form.email_address.trim().includes('@') &&
  !!form.username.trim() &&
  (isEdit.value || !!form.password.trim()) &&
  !!form.imap_host.trim() &&
  !!form.smtp_host.trim(),
)

function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  showForm.value = true
}
function openEdit(a: EmailAccountResponse) {
  editingId.value = a.id
  form.provider = detectProvider(a.imap_host)
  form.label = a.label
  form.email_address = a.email_address
  form.username = a.username
  form.password = ''
  form.display_name = a.display_name ?? ''
  form.imap_host = a.imap_host
  form.imap_port = a.imap_port
  form.imap_use_ssl = a.imap_use_ssl
  form.smtp_host = a.smtp_host
  form.smtp_port = a.smtp_port
  form.smtp_use_tls = a.smtp_use_tls
  form.poll_interval_minutes = a.poll_interval_minutes
  showForm.value = true
}
function cancelForm() {
  showForm.value = false
  editingId.value = null
}

/** Build a create payload from the current form. */
function buildCreatePayload(): EmailAccountCreate {
  return {
    label: form.label.trim() || form.email_address,
    email_address: form.email_address.trim(),
    imap_host: form.imap_host.trim(),
    imap_port: form.imap_port,
    imap_use_ssl: form.imap_use_ssl,
    smtp_host: form.smtp_host.trim(),
    smtp_port: form.smtp_port,
    smtp_use_tls: form.smtp_use_tls,
    username: form.username.trim(),
    password: form.password,
    display_name: form.display_name.trim() || null,
    poll_interval_minutes: form.poll_interval_minutes,
  }
}

/** Build an update payload; password is omitted when blank (keep stored). */
function buildUpdatePayload(): EmailAccountUpdate {
  const { password: _pw, ...rest } = buildCreatePayload()
  void _pw
  return form.password ? { ...rest, password: form.password } : rest
}

async function submit() {
  if (!canSave.value) return
  saving.value = true
  try {
    if (isEdit.value) {
      await emailApi.updateAccount(editingId.value!, buildUpdatePayload())
      emit('toast', 'success', 'Account updated')
    } else {
      await emailApi.createAccount(buildCreatePayload())
      emit('toast', 'success', 'Account added — syncing folders')
    }
    showForm.value = false
    editingId.value = null
    await store.fetchAccounts()
  } catch (e: unknown) {
    emit('toast', 'error', `Could not save account: ${errMsg(e)}`)
  } finally {
    saving.value = false
  }
}

async function testAccount(a?: EmailAccountResponse) {
  testing.value = true
  try {
    let id = editingId.value
    // For an unsaved/new form, persist first so the server can connect.
    if (id == null && !a) {
      if (!canSave.value) { emit('toast', 'error', 'Complete the required fields first'); return }
      const created = await emailApi.createAccount(buildCreatePayload())
      id = created.id
      editingId.value = id
      await store.fetchAccounts()
    } else if (a) {
      id = a.id
    }
    if (id == null) return
    const res = await emailApi.testAccount(id)
    if (res.success) emit('toast', 'success', 'Connection OK')
    else emit('toast', 'error', `Failed: ${res.error}`)
  } catch (e: unknown) {
    emit('toast', 'error', `Test failed: ${errMsg(e)}`)
  } finally {
    testing.value = false
  }
}

async function removeAccount(a: EmailAccountResponse) {
  if (!confirm(`Remove account "${a.label}" and all its cached messages?`)) return
  try {
    await emailApi.deleteAccount(a.id)
    emit('toast', 'info', 'Account removed')
    if (editingId.value === a.id) cancelForm()
    await store.fetchAccounts()
  } catch (e: unknown) {
    emit('toast', 'error', `Could not remove: ${errMsg(e)}`)
  }
}

function fmtSynced(iso: string | null): string {
  if (!iso) return 'never'
  const d = new Date(iso)
  return isNaN(+d) ? iso : d.toLocaleString()
}

onMounted(() => { if (!store.accounts.length) store.fetchAccounts() })
</script>

<template>
  <SettingsSection title="Email accounts" :icon="Mail" description="IMAP/SMTP mailboxes for the Email view"
    setting-key="Email accounts">
    <!-- Add / form toggle -->
    <div class="pb-1">
      <SButton v-if="!showForm" variant="primary" :icon="Plus" @click="openCreate">Add account</SButton>
    </div>

    <!-- Create / edit form -->
    <div v-if="showForm" class="space-y-2.5 rounded-md border border-border bg-surface-hover/40 p-3">
      <div class="flex items-center justify-between">
        <span class="text-[12px] font-semibold text-text-primary">{{ isEdit ? 'Edit account' : 'New account' }}</span>
        <button class="text-text-muted hover:text-text-primary cursor-pointer" @click="cancelForm"><X :size="14" /></button>
      </div>

      <!-- Provider (required) -->
      <div class="flex flex-col gap-1">
        <label class="text-[11px] text-text-muted">Provider <span class="text-danger">*</span></label>
        <select v-model="form.provider" class="settings-select"
          @change="applyProvider(form.provider)">
          <option v-for="p in PROVIDERS" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <p v-if="presetHint" class="text-[10px] text-text-muted leading-snug">{{ presetHint }}</p>
      </div>

      <div class="grid grid-cols-2 gap-2">
        <SettingRow indent label="Email address">
          <input v-model="form.email_address" type="email" placeholder="you@example.com" class="settings-input w-full" />
        </SettingRow>
        <SettingRow indent label="Label">
          <input v-model="form.label" placeholder="Work" class="settings-input w-full" />
        </SettingRow>
        <SettingRow indent label="User ID">
          <input v-model="form.username" placeholder="you@example.com" class="settings-input w-full" />
        </SettingRow>
        <SettingRow indent :label="isEdit ? 'Password (blank = keep)' : 'Password'">
          <input v-model="form.password" type="password" autocomplete="new-password" placeholder="••••••••" class="settings-input w-full" />
        </SettingRow>
      </div>

      <!-- Advanced server config (auto-filled; editable, esp. for Custom) -->
      <AccordionItem :title="isCustom ? 'Server details' : 'Advanced server settings'" :icon="Server" :default-open="isCustom">
        <div class="space-y-2 pt-1">
          <div class="grid grid-cols-[1fr_5rem] gap-2">
            <div>
              <label class="text-[10px] text-text-muted">IMAP host</label>
              <input v-model="form.imap_host" placeholder="imap.example.com" class="settings-input w-full" />
            </div>
            <div>
              <label class="text-[10px] text-text-muted">Port</label>
              <input v-model.number="form.imap_port" type="number" class="settings-input w-full" />
            </div>
          </div>
          <div class="grid grid-cols-[1fr_5rem] gap-2">
            <div>
              <label class="text-[10px] text-text-muted">SMTP host</label>
              <input v-model="form.smtp_host" placeholder="smtp.example.com" class="settings-input w-full" />
            </div>
            <div>
              <label class="text-[10px] text-text-muted">Port</label>
              <input v-model.number="form.smtp_port" type="number" class="settings-input w-full" />
            </div>
          </div>
          <div class="flex items-center gap-4">
            <label class="flex items-center gap-1.5 text-[11px] text-text-secondary">
              <input v-model="form.imap_use_ssl" type="checkbox" class="accent-accent" /> IMAP SSL
            </label>
            <label class="flex items-center gap-1.5 text-[11px] text-text-secondary">
              <input v-model="form.smtp_use_tls" type="checkbox" class="accent-accent" /> SMTP TLS
            </label>
          </div>
        </div>
      </AccordionItem>

      <SettingRow indent label="Display name" description="Shown on outgoing mail (optional)">
        <input v-model="form.display_name" placeholder="Your name" class="settings-input w-full" />
      </SettingRow>
      <SettingRow indent label="Sync every" description="Background poll interval (minutes)">
        <input v-model.number="form.poll_interval_minutes" type="number" min="1" class="settings-input w-20" />
      </SettingRow>

      <div class="flex items-center justify-between gap-2 pt-1">
        <SButton v-if="isEdit" variant="danger-soft" :icon="Trash2" @click="removeAccount(store.accounts.find(a => a.id === editingId)!)" />
        <div v-else />
        <div class="flex items-center gap-2">
          <SButton variant="outline" :icon="PlugZap" :disabled="testing || !canSave" @click="testAccount()">
            <Loader v-if="testing" :size="11" class="animate-spin" /> Test
          </SButton>
          <SButton variant="primary" :icon="Check" :disabled="saving || !canSave" @click="submit">
            <Loader v-if="saving" :size="11" class="animate-spin" /> {{ isEdit ? 'Save' : 'Add account' }}
          </SButton>
        </div>
      </div>
    </div>

    <!-- Account list -->
    <div v-if="store.accounts.length" class="space-y-1 border-t border-border pt-2">
      <div v-for="a in store.accounts" :key="a.id"
        class="flex items-center gap-2 rounded-md bg-surface-hover px-2 py-1.5">
        <Mail :size="12" class="shrink-0 text-accent" />
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-1.5">
            <span class="truncate text-[12px] font-medium text-text-primary">{{ a.label }}</span>
            <span class="shrink-0 rounded-full bg-surface px-1.5 py-0.5 text-[9px] text-text-muted">{{ providerLabel(a) }}</span>
          </div>
          <div class="truncate text-[10px] text-text-muted">{{ a.email_address }}</div>
          <div class="flex items-center gap-1 text-[10px]"
            :class="a.last_sync_error ? 'text-danger' : 'text-text-muted'">
            <AlertTriangle v-if="a.last_sync_error" :size="9" />
            <CheckCircle2 v-else-if="a.last_synced_at" :size="9" class="text-green-500" />
            synced {{ fmtSynced(a.last_synced_at) }}
          </div>
        </div>
        <SButton variant="ghost" size="xs" :icon="Pencil" title="Edit" @click="openEdit(a)" />
        <SButton variant="ghost" size="xs" :icon="PlugZap" title="Test connection" @click="testAccount(a)" />
        <SButton variant="ghost" size="xs" :icon="Trash2" title="Remove" class="!text-text-muted hover:!text-danger" @click="removeAccount(a)" />
      </div>
    </div>
    <div v-else-if="!showForm" class="border-t border-border pt-3 text-center">
      <Mail :size="18" class="mx-auto mb-1 text-text-muted" />
      <p class="text-[11px] text-text-secondary">No email accounts configured.</p>
      <p class="text-[10px] text-text-muted mt-0.5">Add one to read and send mail from the Email view.</p>
    </div>
  </SettingsSection>
</template>
