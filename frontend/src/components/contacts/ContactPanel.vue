<script setup lang="ts">
/**
 * ContactPanel — right-hand detail pane for a selected contact.
 *
 * Two tabs: Overview (read-only field cards) and Related Emails (messages
 * involving this contact's address). The Edit action swaps in <ContactForm>.
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useContactsStore } from '../../stores/contacts'
import * as contactsApi from '../../api/contacts'
import type { ContactResponse, ContactGroupBrief, RelatedEmailResponse, ContactAddress } from '../../types'
import {
  X, Pencil, Star, Mail, Phone, MapPin, Globe, Calendar, MessageSquare,
  Heart, Briefcase, ExternalLink, Building2, Trash2,
} from 'lucide-vue-next'
import ContactForm from './ContactForm.vue'

const props = defineProps<{
  contact: ContactResponse | null
  groups: ContactGroupBrief[]
}>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const store = useContactsStore()

const tab = ref<'overview' | 'emails'>('overview')
const editing = ref(false)
const related = ref<RelatedEmailResponse[]>([])
const loadingEmails = ref(false)

const photoBust = ref(Date.now())
watch(() => props.contact?.id, () => {
  tab.value = 'overview'
  editing.value = false
  photoBust.value = Date.now()
  related.value = []
})

const photoSrc = computed(() =>
  props.contact && props.contact.photo_path
    ? `${contactsApi.photoUrl(props.contact.id)}?${photoBust.value}`
    : null,
)
const initials = computed(() => {
  if (!props.contact) return '?'
  const base = props.contact.name || props.contact.email
  const parts = base.split(/[\s@._]+/).filter(Boolean)
  return parts.length >= 2 ? (parts[0][0] + parts[1][0]).toUpperCase() : base.slice(0, 2).toUpperCase()
})

async function loadEmails() {
  if (!props.contact) return
  loadingEmails.value = true
  try {
    related.value = await contactsApi.listRelatedEmails(props.contact.id)
  } finally {
    loadingEmails.value = false
  }
}
watch(() => [props.contact?.id, tab.value] as const, ([id, t]) => {
  if (id && t === 'emails' && !related.value.length) loadEmails()
})

async function onSaved() {
  editing.value = false
  photoBust.value = Date.now()
  await Promise.all([store.fetchAll(), store.fetchGroups()])
}
async function removeContact() {
  if (!props.contact || !confirm(`Delete "${props.contact.name || props.contact.email}"?`)) return
  await store.remove(props.contact.id)
  emit('close')
}

function fmtAddress(a: ContactAddress) {
  return [a.street, [a.postal_code, a.city].filter(Boolean).join(' '), a.region, a.country]
    .filter(Boolean).join(', ')
}
function fmtDate(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(+d) ? iso : d.toLocaleDateString()
}
const SOURCE_LABELS: Record<string, string> = { manual: 'Manual', email: 'From email', vcard: 'vCard' }
</script>

<template>
  <div v-if="contact" class="flex flex-col h-full bg-surface">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
      <div class="flex items-center gap-1 bg-surface-hover rounded-md p-0.5">
        <button @click="tab = 'overview'"
          class="px-3 py-1 rounded text-[12px] transition-colors cursor-pointer"
          :class="tab === 'overview' ? 'bg-surface text-text-primary font-medium' : 'text-text-secondary hover:text-text-primary'">
          Overview
        </button>
        <button @click="tab = 'emails'"
          class="px-3 py-1 rounded text-[12px] transition-colors cursor-pointer"
          :class="tab === 'emails' ? 'bg-surface text-text-primary font-medium' : 'text-text-secondary hover:text-text-primary'">
          Related emails
        </button>
      </div>
      <div class="flex items-center gap-1">
        <button @click="store.toggleFavorite(contact)" class="p-1.5 rounded-md hover:bg-surface-hover cursor-pointer transition-colors"
          :class="contact.is_favorite ? 'text-yellow-500' : 'text-text-muted'" title="Favorite">
          <Star :size="15" :fill="contact.is_favorite ? 'currentColor' : 'none'" />
        </button>
        <button @click="editing = true" class="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-text-primary cursor-pointer transition-colors" title="Edit">
          <Pencil :size="15" />
        </button>
        <button @click="removeContact" class="p-1.5 rounded-md hover:bg-danger/10 text-text-muted hover:text-danger cursor-pointer transition-colors" title="Delete">
          <Trash2 :size="15" />
        </button>
        <button @click="emit('close')" class="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-text-primary cursor-pointer transition-colors" title="Close">
          <X :size="16" />
        </button>
      </div>
    </div>

    <!-- Edit mode -->
    <ContactForm v-if="editing" :contact="contact" :groups="groups" @saved="onSaved" @cancel="editing = false" />

    <!-- Read mode -->
    <div v-else class="flex-1 overflow-y-auto">
      <!-- Identity card -->
      <div class="flex flex-col items-center text-center px-6 py-6 border-b border-border">
        <div v-if="photoSrc" class="w-20 h-20 rounded-full bg-surface-hover border border-border overflow-hidden mb-3">
          <img :src="photoSrc" :alt="contact.name || ''" class="w-full h-full object-cover" />
        </div>
        <div v-else class="w-20 h-20 rounded-full bg-accent/15 text-accent flex items-center justify-center text-[22px] font-bold mb-3">
          {{ initials }}
        </div>
        <h2 class="text-[16px] font-semibold text-text-primary">{{ contact.name || contact.email }}</h2>
        <p v-if="contact.nickname || contact.title || contact.company" class="text-[12px] text-text-secondary mt-0.5">
          <span v-if="contact.nickname">“{{ contact.nickname }}”</span>
          <span v-if="contact.nickname && (contact.title || contact.company)"> · </span>
          <span>{{ [contact.title, contact.company].filter(Boolean).join(' · ') }}</span>
        </p>
        <div class="flex items-center gap-1.5 mt-2">
          <span v-if="contact.source !== 'manual'"
            class="px-1.5 py-0.5 rounded-full text-[9px] uppercase tracking-wide bg-surface-hover text-text-muted">
            {{ SOURCE_LABELS[contact.source] || contact.source }}
          </span>
          <span v-for="g in contact.groups" :key="g.id"
            class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] bg-surface-hover text-text-secondary">
            <span class="w-1.5 h-1.5 rounded-full" :style="{ background: g.color || 'var(--color-accent)' }"></span>{{ g.name }}
          </span>
        </div>
      </div>

      <!-- Field rows -->
      <div class="divide-y divide-border">
        <!-- Emails -->
        <div class="px-5 py-3 flex items-start gap-3">
          <Mail :size="14" class="text-text-muted mt-0.5 shrink-0" />
          <div class="min-w-0">
            <div class="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">Email</div>
            <a :href="`mailto:${contact.email}`" class="block text-[13px] text-accent hover:underline truncate">{{ contact.email }}</a>
            <a v-for="e in contact.emails_extra" :key="e" :href="`mailto:${e}`" class="block text-[13px] text-accent hover:underline truncate">{{ e }}</a>
          </div>
        </div>

        <!-- Phones -->
        <div v-if="contact.phones?.length" class="px-5 py-3 flex items-start gap-3">
          <Phone :size="14" class="text-text-muted mt-0.5 shrink-0" />
          <div class="min-w-0">
            <div class="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">Phone</div>
            <a v-for="(p, i) in contact.phones" :key="i" :href="`tel:${p.value}`"
              class="block text-[13px] text-text-primary hover:text-accent capitalize">
              <span class="text-text-muted">{{ p.type }}:</span> {{ p.value }}
            </a>
          </div>
        </div>

        <!-- Company / business -->
        <div v-if="contact.company || contact.department || contact.profession" class="px-5 py-3 flex items-start gap-3">
          <Briefcase :size="14" class="text-text-muted mt-0.5 shrink-0" />
          <div class="min-w-0">
            <div class="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">Business</div>
            <p class="text-[13px] text-text-primary">
              <span v-if="contact.title">{{ contact.title }}</span><span v-if="contact.title && contact.company"> at </span>
              <span v-if="contact.company" class="inline-flex items-center gap-1"><Building2 :size="11" />{{ contact.company }}</span>
            </p>
            <p v-if="contact.department || contact.profession" class="text-[12px] text-text-secondary">
              {{ [contact.department, contact.profession].filter(Boolean).join(' · ') }}
            </p>
          </div>
        </div>

        <!-- Addresses -->
        <div v-if="contact.addresses?.length" class="px-5 py-3 flex items-start gap-3">
          <MapPin :size="14" class="text-text-muted mt-0.5 shrink-0" />
          <div class="min-w-0">
            <div class="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">Address</div>
            <p v-for="(a, i) in contact.addresses" :key="i" class="text-[13px] text-text-primary capitalize">
              <span class="text-text-muted">{{ a.type }}:</span> {{ fmtAddress(a) }}
            </p>
          </div>
        </div>

        <!-- Internet -->
        <div v-if="contact.websites?.length || contact.im_handles?.length" class="px-5 py-3 flex items-start gap-3">
          <Globe :size="14" class="text-text-muted mt-0.5 shrink-0" />
          <div class="min-w-0 space-y-0.5">
            <div class="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">Internet</div>
            <a v-for="(w, i) in contact.websites" :key="'w'+i" :href="w" target="_blank" rel="noopener"
              class="flex items-center gap-1 text-[13px] text-accent hover:underline truncate">
              <ExternalLink :size="11" /> {{ w }}
            </a>
            <p v-for="(im, i) in contact.im_handles" :key="'im'+i" class="text-[13px] text-text-primary capitalize">
              <MessageSquare :size="11" class="inline text-text-muted" /> <span class="text-text-muted">{{ im.type }}:</span> {{ im.value }}
            </p>
          </div>
        </div>

        <!-- Dates -->
        <div v-if="contact.dates?.length" class="px-5 py-3 flex items-start gap-3">
          <Calendar :size="14" class="text-text-muted mt-0.5 shrink-0" />
          <div class="min-w-0">
            <div class="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">Dates</div>
            <p v-for="(d, i) in contact.dates" :key="i" class="text-[13px] text-text-primary capitalize">
              <span class="text-text-muted">{{ d.type }}:</span> {{ fmtDate(d.date) }}
            </p>
          </div>
        </div>

        <!-- Relationships -->
        <div v-if="contact.relationships?.length" class="px-5 py-3 flex items-start gap-3">
          <Heart :size="14" class="text-text-muted mt-0.5 shrink-0" />
          <div class="min-w-0">
            <div class="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">Relationships</div>
            <p v-for="(r, i) in contact.relationships" :key="i" class="text-[13px] text-text-primary capitalize">
              <span class="text-text-muted">{{ r.type }}:</span> {{ r.value }}
            </p>
          </div>
        </div>

        <!-- Notes -->
        <div v-if="contact.notes" class="px-5 py-3 flex items-start gap-3">
          <MessageSquare :size="14" class="text-text-muted mt-0.5 shrink-0" />
          <div class="min-w-0">
            <div class="text-[11px] uppercase tracking-wide text-text-muted mb-0.5">Notes</div>
            <p class="text-[13px] text-text-primary whitespace-pre-wrap">{{ contact.notes }}</p>
          </div>
        </div>
      </div>

      <!-- Related emails tab content -->
      <div v-if="tab === 'emails'" class="px-5 py-3">
        <div v-if="loadingEmails" class="text-[12px] text-text-muted py-4 text-center">Loading…</div>
        <div v-else-if="!related.length" class="text-[12px] text-text-muted py-6 text-center">No emails found for this contact.</div>
        <div v-else class="space-y-1.5">
          <button v-for="m in related" :key="m.id" @click="router.push('/email')"
            class="w-full text-left flex items-start gap-2 p-2.5 rounded-md border border-border hover:border-accent/40 transition-colors cursor-pointer">
            <Mail :size="14" class="text-text-muted mt-0.5 shrink-0" />
            <div class="min-w-0">
              <p class="text-[13px] font-medium text-text-primary truncate">{{ m.subject || '(no subject)' }}</p>
              <p class="text-[11px] text-text-secondary truncate">
                {{ m.from_name || m.from_address }} · {{ fmtDate(m.sent_at) }}
              </p>
            </div>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Empty state -->
  <div v-else class="flex flex-col items-center justify-center h-full text-center px-6">
    <div class="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mb-3">
      <Mail :size="22" class="text-accent/60" />
    </div>
    <p class="text-[13px] text-text-secondary">Select a contact to see details</p>
  </div>
</template>
