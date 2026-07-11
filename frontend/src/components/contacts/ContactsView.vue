<script setup lang="ts">
/**
 * ContactsView — address book with manual CRUD, vCard import/export.
 *
 * Auto-extracted contacts (source="email") and vCard imports (source="vcard")
 * are shown alongside manually-created ones. Source is surfaced as a small
 * badge so the origin of each contact is clear.
 */
import { computed, onMounted, ref } from 'vue'
import { useContactsStore } from '../../stores/contacts'
import * as contactsApi from '../../api/contacts'
import type { ContactResponse, ContactCreate } from '../../types'
import {
  Users, UserPlus, Plus, Trash2, Pencil, X, Check, Download, Upload,
  Search, Mail, Phone, Building2, AlertCircle, CheckCircle2, Info,
} from 'lucide-vue-next'

const store = useContactsStore()

// ── Form state ──
const showForm = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const emptyForm = (): ContactCreate => ({ name: '', email: '', phone: '', company: '', title: '', notes: '' })
const form = ref<ContactCreate>(emptyForm())
const fileInput = ref<HTMLInputElement | null>(null)

// ── Toast ──
const toast = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error' | 'info', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3200)
}

onMounted(() => store.fetchAll())

let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => store.fetchAll(), 250)
}

const sortedContacts = computed(() =>
  [...store.contacts].sort((a, b) => (a.name || a.email).localeCompare(b.name || b.email)),
)

function initials(c: ContactResponse): string {
  const base = c.name || c.email
  const parts = base.split(/[\s@._]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return base.slice(0, 2).toUpperCase()
}

const SOURCE_LABELS: Record<string, string> = { manual: 'Manual', email: 'From email', vcard: 'vCard' }

// ── CRUD actions ──
function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  showForm.value = true
}
function openEdit(c: ContactResponse) {
  editingId.value = c.id
  form.value = {
    name: c.name ?? '',
    email: c.email,
    phone: c.phone ?? '',
    company: c.company ?? '',
    title: c.title ?? '',
    notes: c.notes ?? '',
  }
  showForm.value = true
}
function cancelForm() {
  showForm.value = false
  editingId.value = null
}
async function submitForm() {
  if (!form.value.email.trim()) { showToast('error', 'Email is required'); return }
  submitting.value = true
  try {
    if (editingId.value !== null) {
      await store.update(editingId.value, { ...form.value })
      showToast('success', 'Contact updated')
    } else {
      await store.create({ ...form.value })
      showToast('success', 'Contact added')
    }
    cancelForm()
  } catch (e) {
    showToast('error', e instanceof Error && e.message.includes('409')
      ? 'A contact with that email already exists'
      : 'Could not save contact')
  } finally {
    submitting.value = false
  }
}
async function removeContact(c: ContactResponse) {
  if (!confirm(`Delete "${c.name || c.email}"?`)) return
  try {
    await store.remove(c.id)
    showToast('info', 'Contact deleted')
  } catch {
    showToast('error', 'Could not delete contact')
  }
}
async function onImportFile(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  try {
    const res = await contactsApi.importContacts(file)
    await store.fetchAll()
    showToast('success', `Imported ${res.imported} contact${res.imported === 1 ? '' : 's'}`)
  } catch {
    showToast('error', 'Import failed')
  } finally {
    target.value = ''
  }
}
async function doExport() {
  try {
    await contactsApi.exportContacts()
    showToast('success', 'Exported contacts.vcf')
  } catch {
    showToast('error', 'Export failed')
  }
}
</script>

<template>
  <div class="relative h-full overflow-y-auto px-6 py-5 space-y-5">
    <!-- Header -->
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
          <Users :size="20" class="text-accent" />
        </div>
        <div>
          <h1 class="text-xl font-bold text-text-primary leading-tight">Contacts</h1>
          <p class="text-[11px] text-text-muted mt-0.5">
            <span class="font-medium text-accent">{{ store.total }}</span>
            <span class="text-text-secondary"> total</span>
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button @click="fileInput?.click()" title="Import .vcf"
          class="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-hover text-text-secondary text-[12px] rounded-md hover:bg-border transition-colors cursor-pointer border border-border">
          <Upload :size="13" /> Import
        </button>
        <input ref="fileInput" type="file" accept=".vcf,text/vcard" class="hidden" @change="onImportFile" />
        <button @click="doExport" title="Export to .vcf"
          class="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-hover text-text-secondary text-[12px] rounded-md hover:bg-border transition-colors cursor-pointer border border-border">
          <Download :size="13" /> Export
        </button>
        <button @click="openCreate"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover transition-colors cursor-pointer shadow-sm">
          <Plus :size="14" /> New
        </button>
      </div>
    </div>

    <!-- Search -->
    <div class="relative">
      <Search :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
      <input v-model="store.search" @input="onSearchInput" placeholder="Search by name, email, phone, company…"
        class="w-full pl-9 pr-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />
    </div>

    <!-- Create / Edit form -->
    <Transition name="form-slide">
      <div v-if="showForm" class="bg-surface rounded-lg p-4 border border-accent/30 shadow-sm space-y-3">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-accent flex items-center gap-1.5">
            <UserPlus :size="11" /> {{ editingId !== null ? 'Edit contact' : 'New contact' }}
          </span>
          <button @click="cancelForm" class="p-1 rounded hover:bg-surface-hover text-text-muted cursor-pointer"><X :size="13" /></button>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input v-model="form.name" placeholder="Full name"
            class="px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />
          <input v-model="form.email" type="email" placeholder="Email *"
            class="px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />
          <input v-model="form.phone" placeholder="Phone"
            class="px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />
          <input v-model="form.company" placeholder="Company"
            class="px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />
          <input v-model="form.title" placeholder="Job title"
            class="px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors sm:col-span-2" />
        </div>
        <textarea v-model="form.notes" placeholder="Notes (optional)" rows="2"
          class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors resize-none" />

        <div class="flex gap-2 pt-1">
          <button @click="submitForm" :disabled="submitting"
            class="inline-flex items-center gap-1.5 px-4 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover disabled:opacity-50 transition-colors cursor-pointer">
            <Check :size="13" /> {{ editingId !== null ? 'Save changes' : 'Add contact' }}
          </button>
          <button @click="cancelForm"
            class="px-3 py-1.5 bg-surface-hover text-text-secondary text-[12px] rounded-md hover:bg-border transition-colors cursor-pointer">
            Cancel
          </button>
        </div>
      </div>
    </Transition>

    <!-- Loading -->
    <div v-if="store.loading" class="text-center py-10 text-text-muted text-[13px]">Loading contacts…</div>

    <!-- Empty state -->
    <div v-else-if="store.contacts.length === 0"
      class="text-center py-12 px-6 rounded-lg border border-dashed border-border bg-surface/50">
      <div class="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mx-auto mb-3">
        <Users :size="24" class="text-accent/70" />
      </div>
      <h3 class="text-[14px] font-medium text-text-primary">No contacts yet</h3>
      <p class="text-[12px] text-text-secondary mt-1 max-w-sm mx-auto leading-relaxed">
        Add contacts manually, import a .vcf file, or they'll be collected automatically
        from your email correspondence.
      </p>
      <button @click="openCreate"
        class="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover transition-colors cursor-pointer">
        <Plus :size="14" /> Add your first contact
      </button>
    </div>

    <!-- Contact list -->
    <div v-else class="space-y-2">
      <div v-for="c in sortedContacts" :key="c.id"
        class="group bg-surface rounded-lg p-3 border border-border hover:border-accent/40 transition-all">
        <div class="flex items-start justify-between gap-3">
          <!-- Left: avatar + content -->
          <div class="flex items-start gap-3 min-w-0 flex-1">
            <div class="shrink-0 w-9 h-9 rounded-full bg-accent/15 text-accent flex items-center justify-center text-[11px] font-bold">
              {{ initials(c) }}
            </div>
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-[13px] font-medium text-text-primary truncate">
                  {{ c.name || c.email }}
                </span>
                <span v-if="c.source !== 'manual'"
                  class="px-1.5 py-0.5 rounded-full text-[9px] uppercase tracking-wide bg-surface-hover text-text-muted">
                  {{ SOURCE_LABELS[c.source] || c.source }}
                </span>
              </div>
              <div class="flex flex-col gap-0.5 mt-0.5 text-[11.5px] text-text-secondary">
                <span class="flex items-center gap-1.5 truncate"><Mail :size="11" /> {{ c.email }}</span>
                <span v-if="c.phone" class="flex items-center gap-1.5 truncate"><Phone :size="11" /> {{ c.phone }}</span>
                <span v-if="c.company || c.title" class="flex items-center gap-1.5 truncate">
                  <Building2 :size="11" /> {{ [c.title, c.company].filter(Boolean).join(' · ') }}
                </span>
              </div>
            </div>
          </div>

          <!-- Right: actions -->
          <div class="flex items-center gap-1 shrink-0">
            <button @click="openEdit(c)" title="Edit"
              class="p-1.5 rounded hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors cursor-pointer">
              <Pencil :size="13" />
            </button>
            <button @click="removeContact(c)" title="Delete"
              class="p-1.5 rounded hover:bg-danger/10 text-text-muted hover:text-danger transition-colors cursor-pointer">
              <Trash2 :size="13" />
            </button>
          </div>
        </div>
      </div>
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
        <Info v-else :size="14" />
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
