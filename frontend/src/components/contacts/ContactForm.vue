<script setup lang="ts">
/**
 * ContactForm — EPIM-style sectioned contact editor.
 *
 * Multi-value typed fields (phones, addresses, IM, dates, relationships,
 * websites, extra emails) each render as add/remove rows with a type selector.
 * Group membership is a colour-chip multi-select. Photo upload is available in
 * edit mode (a contact must exist before it can have a photo).
 */
import { computed, ref, watch } from 'vue'
import * as contactsApi from '../../api/contacts'
import type {
  ContactResponse, ContactCreate, ContactUpdate,
  ContactTypedValue, ContactAddress, ContactDateValue, ContactGroupBrief,
} from '../../types'
import {
  X, Check, Plus, Trash2, Star, Camera, User, Phone, Mail, MapPin, Globe,
  Calendar, Users as UsersIcon, Briefcase, MessageSquare, Heart,
} from 'lucide-vue-next'

const props = defineProps<{
  contact: ContactResponse | null
  groups: ContactGroupBrief[]
}>()
const emit = defineEmits<{ saved: []; cancel: [] }>()

const PHONE_TYPES = ['mobile', 'home', 'work', 'fax', 'pager', 'other']
const ADDRESS_TYPES = ['home', 'work', 'other']
const DATE_TYPES = ['birthday', 'anniversary', 'other']
const IM_TYPES = ['skype', 'telegram', 'whatsapp', 'signal', 'other']
const REL_TYPES = ['spouse', 'child', 'parent', 'manager', 'assistant', 'friend', 'other']

const submitting = ref(false)
const uploadingPhoto = ref(false)
const photoBust = ref(Date.now())

function blank() {
  return {
    name: '',
    nickname: '',
    email: '',
    emails_extra: [] as string[],
    company: '',
    department: '',
    title: '',
    profession: '',
    phones: [] as ContactTypedValue[],
    addresses: [] as ContactAddress[],
    im_handles: [] as ContactTypedValue[],
    websites: [] as string[],
    dates: [] as ContactDateValue[],
    relationships: [] as ContactTypedValue[],
    notes: '',
    is_favorite: false,
    group_ids: [] as number[],
  }
}

const form = ref(blank())

watch(
  () => props.contact,
  (c) => {
    photoBust.value = Date.now()
    if (!c) {
      form.value = blank()
      return
    }
    form.value = {
      name: c.name ?? '',
      nickname: c.nickname ?? '',
      email: c.email,
      emails_extra: [...(c.emails_extra ?? [])],
      company: c.company ?? '',
      department: c.department ?? '',
      title: c.title ?? '',
      profession: c.profession ?? '',
      phones: (c.phones ?? []).map((p) => ({ ...p })),
      addresses: (c.addresses ?? []).map((a) => ({ ...a })),
      im_handles: (c.im_handles ?? []).map((i) => ({ ...i })),
      websites: [...(c.websites ?? [])],
      dates: (c.dates ?? []).map((d) => ({ ...d })),
      relationships: (c.relationships ?? []).map((r) => ({ ...r })),
      notes: c.notes ?? '',
      is_favorite: c.is_favorite,
      group_ids: c.groups.map((g) => g.id),
    }
  },
  { immediate: true },
)

const isEdit = computed(() => props.contact !== null)

// ── multi-value helpers ──
function addPhone() { form.value.phones.push({ type: 'mobile', value: '' }) }
function addAddress() { form.value.addresses.push({ type: 'home', street: '', city: '', region: '', postal_code: '', country: '' }) }
function addIm() { form.value.im_handles.push({ type: 'skype', value: '' }) }
function addWebsite() { form.value.websites.push('') }
function addDate() { form.value.dates.push({ type: 'birthday', label: null, date: '' }) }
function addRel() { form.value.relationships.push({ type: 'spouse', value: '' }) }
function addExtraEmail() { form.value.emails_extra.push('') }

const removeAt = <T,>(arr: T[], i: number) => arr.splice(i, 1)

// ── groups ──
function toggleGroup(id: number) {
  const idx = form.value.group_ids.indexOf(id)
  if (idx >= 0) form.value.group_ids.splice(idx, 1)
  else form.value.group_ids.push(id)
}

// ── photo ──
async function onPhoto(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file || !props.contact) return
  uploadingPhoto.value = true
  try {
    await contactsApi.uploadPhoto(props.contact.id, file)
    photoBust.value = Date.now()
  } finally {
    uploadingPhoto.value = false
    ;(e.target as HTMLInputElement).value = ''
  }
}
async function removePhoto() {
  if (!props.contact) return
  await contactsApi.deletePhoto(props.contact.id)
  photoBust.value = Date.now()
}
const photoSrc = computed(() =>
  props.contact && props.contact.photo_path
    ? `${contactsApi.photoUrl(props.contact.id)}?${photoBust.value}`
    : null,
)
const avatarText = computed(() => {
  const base = form.value.name || form.value.email || '?'
  const parts = base.split(/[\s@._]+/).filter(Boolean)
  return parts.length >= 2 ? (parts[0][0] + parts[1][0]).toUpperCase() : base.slice(0, 2).toUpperCase()
})

// ── submit ──
function buildPayload(): ContactCreate {
  const f = form.value
  const clean = (s: string) => s.trim()
  // Send scalar fields as raw (possibly empty) strings rather than coercing to
  // null: the backend PATCH treats a key as "unchanged" when it's None, so an
  // empty string is what actually clears a field.
  return {
    name: clean(f.name),
    nickname: clean(f.nickname),
    email: clean(f.email),
    emails_extra: f.emails_extra.map((e) => e.trim()).filter(Boolean),
    company: clean(f.company),
    department: clean(f.department),
    title: clean(f.title),
    profession: clean(f.profession),
    phones: f.phones.filter((p) => p.value.trim()),
    addresses: f.addresses.filter((a) => Object.values(a).some((v) => v && String(v).trim())),
    im_handles: f.im_handles.filter((i) => i.value.trim()),
    websites: f.websites.map((w) => w.trim()).filter(Boolean),
    dates: f.dates.filter((d) => d.date),
    relationships: f.relationships.filter((r) => r.value.trim()),
    notes: clean(f.notes),
    is_favorite: f.is_favorite,
    group_ids: f.group_ids,
  }
}

async function submit() {
  if (!form.value.email.trim()) return
  submitting.value = true
  try {
    if (props.contact) {
      const patch: ContactUpdate = { ...buildPayload() }
      await contactsApi.updateContact(props.contact.id, patch)
    } else {
      await contactsApi.createContact(buildPayload())
    }
    emit('saved')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="flex flex-col h-full bg-surface">
    <!-- Header -->
    <div class="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
      <h2 class="text-[14px] font-semibold text-text-primary flex items-center gap-2">
        <User :size="15" class="text-accent" />
        {{ isEdit ? 'Edit contact' : 'New contact' }}
      </h2>
      <button @click="emit('cancel')"
        class="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors cursor-pointer">
        <X :size="16" />
      </button>
    </div>

    <!-- Scrollable body -->
    <div class="flex-1 overflow-y-auto px-5 py-4 space-y-5">
      <!-- Photo + name header -->
      <div class="flex items-center gap-4">
        <div class="relative shrink-0">
          <div v-if="photoSrc"
            class="w-16 h-16 rounded-full bg-surface-hover border border-border overflow-hidden">
            <img :src="photoSrc" :alt="form.name" class="w-full h-full object-cover" />
          </div>
          <div v-else
            class="w-16 h-16 rounded-full bg-accent/15 text-accent flex items-center justify-center text-[18px] font-bold border border-accent/20">
            {{ avatarText }}
          </div>
          <label v-if="isEdit"
            class="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-accent text-white flex items-center justify-center cursor-pointer shadow-sm hover:bg-accent-hover transition-colors"
            title="Upload photo">
            <Camera :size="12" />
            <input type="file" accept="image/*" class="hidden" @change="onPhoto" :disabled="uploadingPhoto" />
          </label>
          <button v-if="isEdit && photoSrc" @click="removePhoto"
            class="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-surface text-danger border border-border flex items-center justify-center shadow-sm hover:bg-danger/10 transition-colors"
            title="Remove photo">
            <X :size="10" />
          </button>
        </div>
        <div class="flex-1 min-w-0 space-y-2">
          <input v-model="form.name" placeholder="Full name"
            class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[14px] font-medium text-text-primary outline-none focus:border-accent transition-colors" />
          <div class="flex items-center gap-2">
            <input v-model="form.nickname" placeholder="Nickname"
              class="flex-1 px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-secondary outline-none focus:border-accent transition-colors" />
            <button @click="form.is_favorite = !form.is_favorite"
              class="p-1.5 rounded-md transition-colors cursor-pointer shrink-0"
              :class="form.is_favorite ? 'text-yellow-500 bg-yellow-500/10' : 'text-text-muted hover:bg-surface-hover'"
              title="Favorite">
              <Star :size="16" :fill="form.is_favorite ? 'currentColor' : 'none'" />
            </button>
          </div>
        </div>
      </div>
      <p v-if="!isEdit" class="text-[11px] text-text-muted -mt-2">
        Save the contact first to add a photo.
      </p>

      <!-- Company -->
      <section class="space-y-2.5">
        <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
          <Briefcase :size="11" /> Company
        </h3>
        <div class="grid grid-cols-2 gap-2">
          <input v-model="form.company" placeholder="Company"
            class="px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <input v-model="form.department" placeholder="Department"
            class="px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <input v-model="form.title" placeholder="Job title"
            class="px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <input v-model="form.profession" placeholder="Profession"
            class="px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
        </div>
      </section>

      <!-- Phones -->
      <section class="space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
            <Phone :size="11" /> Phones
          </h3>
          <button @click="addPhone" class="p-1 rounded hover:bg-surface-hover text-accent cursor-pointer"><Plus :size="13" /></button>
        </div>
        <div v-for="(p, i) in form.phones" :key="i" class="flex items-center gap-2">
          <select v-model="p.type"
            class="w-24 px-2 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-secondary outline-none focus:border-accent capitalize">
            <option v-for="t in PHONE_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
          <input v-model="p.value" placeholder="+1 555…"
            class="flex-1 px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <button @click="removeAt(form.phones, i)" class="p-1 text-text-muted hover:text-danger cursor-pointer"><Trash2 :size="13" /></button>
        </div>
      </section>

      <!-- Emails (primary + extras) -->
      <section class="space-y-2">
        <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
          <Mail :size="11" /> Email
        </h3>
        <input v-model="form.email" type="email" placeholder="Primary email *"
          class="w-full px-3 py-1.5 bg-surface-hover border border-accent/40 rounded-md text-[12px] font-medium text-text-primary outline-none focus:border-accent transition-colors" />
        <div v-for="(_, i) in form.emails_extra" :key="i" class="flex items-center gap-2">
          <span class="w-24 text-[11px] text-text-muted">Other</span>
          <input v-model="form.emails_extra[i]" type="email" placeholder="Another email"
            class="flex-1 px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <button @click="removeAt(form.emails_extra, i)" class="p-1 text-text-muted hover:text-danger cursor-pointer"><Trash2 :size="13" /></button>
        </div>
        <button @click="addExtraEmail" class="text-[11px] text-accent hover:underline cursor-pointer flex items-center gap-1">
          <Plus :size="11" /> Add email
        </button>
      </section>

      <!-- Addresses -->
      <section class="space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
            <MapPin :size="11" /> Addresses
          </h3>
          <button @click="addAddress" class="p-1 rounded hover:bg-surface-hover text-accent cursor-pointer"><Plus :size="13" /></button>
        </div>
        <div v-for="(a, i) in form.addresses" :key="i"
          class="space-y-1.5 p-2.5 rounded-md border border-border bg-surface-hover/50">
          <div class="flex items-center gap-2">
            <select v-model="a.type"
              class="w-24 px-2 py-1 bg-surface border border-border rounded-md text-[12px] text-text-secondary outline-none focus:border-accent capitalize">
              <option v-for="t in ADDRESS_TYPES" :key="t" :value="t">{{ t }}</option>
            </select>
            <input v-model="a.street" placeholder="Street"
              class="flex-1 px-3 py-1 bg-surface border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
            <button @click="removeAt(form.addresses, i)" class="p-1 text-text-muted hover:text-danger cursor-pointer"><Trash2 :size="13" /></button>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <input v-model="a.city" placeholder="City"
              class="px-3 py-1 bg-surface border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
            <input v-model="a.region" placeholder="State / Region"
              class="px-3 py-1 bg-surface border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
            <input v-model="a.postal_code" placeholder="Postal code"
              class="px-3 py-1 bg-surface border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
            <input v-model="a.country" placeholder="Country"
              class="px-3 py-1 bg-surface border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          </div>
        </div>
      </section>

      <!-- Internet: IM + websites -->
      <section class="space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
            <Globe :size="11" /> Internet
          </h3>
          <div class="flex items-center gap-1">
            <button @click="addIm" class="p-1 rounded hover:bg-surface-hover text-accent cursor-pointer" title="Add messenger"><MessageSquare :size="13" /></button>
            <button @click="addWebsite" class="p-1 rounded hover:bg-surface-hover text-accent cursor-pointer" title="Add website"><Plus :size="13" /></button>
          </div>
        </div>
        <div v-for="(im, i) in form.im_handles" :key="'im'+i" class="flex items-center gap-2">
          <select v-model="im.type"
            class="w-24 px-2 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-secondary outline-none focus:border-accent capitalize">
            <option v-for="t in IM_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
          <input v-model="im.value" placeholder="Handle"
            class="flex-1 px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <button @click="removeAt(form.im_handles, i)" class="p-1 text-text-muted hover:text-danger cursor-pointer"><Trash2 :size="13" /></button>
        </div>
        <div v-for="(_, i) in form.websites" :key="'w'+i" class="flex items-center gap-2">
          <span class="w-24 text-[11px] text-text-muted">Website</span>
          <input v-model="form.websites[i]" placeholder="https://…"
            class="flex-1 px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <button @click="removeAt(form.websites, i)" class="p-1 text-text-muted hover:text-danger cursor-pointer"><Trash2 :size="13" /></button>
        </div>
      </section>

      <!-- Dates -->
      <section class="space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
            <Calendar :size="11" /> Dates
          </h3>
          <button @click="addDate" class="p-1 rounded hover:bg-surface-hover text-accent cursor-pointer"><Plus :size="13" /></button>
        </div>
        <div v-for="(d, i) in form.dates" :key="i" class="flex items-center gap-2">
          <select v-model="d.type"
            class="w-28 px-2 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-secondary outline-none focus:border-accent capitalize">
            <option v-for="t in DATE_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
          <input v-model="d.date" type="date"
            class="flex-1 px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <button @click="removeAt(form.dates, i)" class="p-1 text-text-muted hover:text-danger cursor-pointer"><Trash2 :size="13" /></button>
        </div>
      </section>

      <!-- Relationships -->
      <section class="space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
            <Heart :size="11" /> Relationships
          </h3>
          <button @click="addRel" class="p-1 rounded hover:bg-surface-hover text-accent cursor-pointer"><Plus :size="13" /></button>
        </div>
        <div v-for="(r, i) in form.relationships" :key="i" class="flex items-center gap-2">
          <select v-model="r.type"
            class="w-28 px-2 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-secondary outline-none focus:border-accent capitalize">
            <option v-for="t in REL_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
          <input v-model="r.value" placeholder="Name"
            class="flex-1 px-3 py-1.5 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors" />
          <button @click="removeAt(form.relationships, i)" class="p-1 text-text-muted hover:text-danger cursor-pointer"><Trash2 :size="13" /></button>
        </div>
      </section>

      <!-- Groups -->
      <section v-if="groups.length" class="space-y-2">
        <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
          <UsersIcon :size="11" /> Groups
        </h3>
        <div class="flex flex-wrap gap-1.5">
          <button v-for="g in groups" :key="g.id" @click="toggleGroup(g.id)"
            class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] border transition-colors cursor-pointer"
            :class="form.group_ids.includes(g.id)
              ? 'bg-accent/15 border-accent/40 text-text-primary'
              : 'bg-surface-hover border-border text-text-secondary hover:border-accent/30'">
            <span class="w-2 h-2 rounded-full" :style="{ background: g.color || 'var(--color-accent)' }"></span>
            {{ g.name }}
          </button>
        </div>
      </section>

      <!-- Notes -->
      <section class="space-y-2">
        <h3 class="text-[11px] font-semibold uppercase tracking-wide text-text-muted">Notes</h3>
        <textarea v-model="form.notes" rows="3" placeholder="Notes…"
          class="w-full px-3 py-2 bg-surface-hover border border-border rounded-md text-[12px] text-text-primary outline-none focus:border-accent transition-colors resize-none" />
      </section>
    </div>

    <!-- Footer -->
    <div class="flex items-center justify-end gap-2 px-5 py-3 border-t border-border shrink-0">
      <button @click="emit('cancel')"
        class="px-3 py-1.5 bg-surface-hover text-text-secondary text-[12px] rounded-md hover:bg-border transition-colors cursor-pointer">
        Cancel
      </button>
      <button @click="submit" :disabled="submitting || !form.email.trim()"
        class="inline-flex items-center gap-1.5 px-4 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover disabled:opacity-50 transition-colors cursor-pointer">
        <Check :size="13" /> {{ isEdit ? 'Save changes' : 'Add contact' }}
      </button>
    </div>
  </div>
</template>
