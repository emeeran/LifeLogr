<script setup lang="ts">
/**
 * ContactsView — EPIM-style 3-pane workspace.
 *
 *   ┌──────────┬────────────────────┬──────────────┐
 *   │ groups   │ letter-bar + list  │ detail panel │
 *   │ rail     │ (A–Z grouped)      │ (overview /  │
 *   │          │                    │  emails)     │
 *   └──────────┴────────────────────┴──────────────┘
 *
 * The detail panel embeds <ContactForm> for editing; a slide-over form is used
 * for creating new contacts.
 */
import { computed, onMounted, ref } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { useContactsStore } from '../../stores/contacts'
import * as contactsApi from '../../api/contacts'
import type { ContactResponse } from '../../types'
import {
  Users, Plus, Search, Star, Upload, Download, X, Pencil, AlertCircle, CheckCircle2, Info,
} from 'lucide-vue-next'
import ContactPanel from './ContactPanel.vue'
import ContactForm from './ContactForm.vue'
import { useLocalStorage } from '@vueuse/core'
import PanelSplitter from '../layout/PanelSplitter.vue'

const store = useContactsStore()

// ── Resizable panes (persisted) ──
const groupsWidth = useLocalStorage<number>('lifelogr-contacts-groups-width', 208)
const detailWidth = useLocalStorage<number>('lifelogr-contacts-detail-width', 380)

const selectedId = ref<number | null>(null)
const showCreateForm = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

// ── Toast ──
const toast = ref<{ type: 'success' | 'error' | 'info'; message: string } | null>(null)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function showToast(type: 'success' | 'error' | 'info', message: string) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, message }
  toastTimer = setTimeout(() => { toast.value = null }, 3200)
}

onMounted(async () => {
  await Promise.all([store.fetchAll(), store.fetchGroups()])
})

let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => store.fetchAll(), 250)
}

const selected = computed(() => store.contacts.find((c) => c.id === selectedId.value) ?? null)

const sorted = computed(() =>
  [...store.contacts].sort((a, b) => (a.name || a.email).localeCompare(b.name || b.email)),
)
const grouped = computed(() => {
  const map = new Map<string, ContactResponse[]>()
  for (const c of sorted.value) {
    const key = (c.name || c.email).charAt(0).toUpperCase()
    const k = /[A-Z]/.test(key) ? key : '#'
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(c)
  }
  return [...map.entries()].sort((a, b) => (a[0] === '#' ? 1 : b[0] === '#' ? -1 : a[0].localeCompare(b[0])))
})
const presentLetters = computed(() => grouped.value.map((g) => g[0]))

// Flatten the A–Z groups into one virtualizable array (header + rows). Only the
// visible slice is rendered, so thousands of contacts don't inflate the DOM.
interface FlatItem { kind: 'header' | 'row'; letter: string; contact: ContactResponse | null }
const flat = computed<FlatItem[]>(() => {
  const out: FlatItem[] = []
  for (const [letter, items] of grouped.value) {
    out.push({ kind: 'header', letter, contact: null })
    for (const c of items) out.push({ kind: 'row', letter, contact: c })
  }
  return out
})
const listScrollEl = ref<HTMLElement | null>(null)
const virtualizer = useVirtualizer(
  computed(() => ({
    count: flat.value.length,
    getScrollElement: () => listScrollEl.value,
    estimateSize: (i: number) => (flat.value[i].kind === 'header' ? 26 : 48),
    overscan: 8,
  })),
)

function initials(c: ContactResponse): string {
  const base = c.name || c.email
  const parts = base.split(/[\s@._]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return base.slice(0, 2).toUpperCase()
}
function photoFor(c: ContactResponse) {
  return c.photo_path ? `${contactsApi.photoUrl(c.id)}` : null
}

function selectContact(c: ContactResponse) {
  selectedId.value = c.id
}
function scrollToLetter(letter: string) {
  const idx = flat.value.findIndex((it) => it.kind === 'header' && it.letter === letter)
  if (idx >= 0) virtualizer.value.scrollToIndex(idx, { align: 'start' })
}

function openCreate() {
  showCreateForm.value = true
}
async function onCreated() {
  showCreateForm.value = false
  showToast('success', 'Contact added')
}

async function addGroup() {
  const name = prompt('Group name')
  if (!name?.trim()) return
  try {
    await store.createGroup(name.trim())
    showToast('success', 'Group added')
  } catch (e) {
    showToast('error', e instanceof Error && e.message.includes('409') ? 'A group with that name exists' : 'Could not create group')
  }
}
async function renameGroup(id: number, oldName: string) {
  const name = prompt('Rename group', oldName)
  if (!name?.trim() || name.trim() === oldName) return
  try {
    await store.updateGroup(id, name.trim())
  } catch {
    showToast('error', 'Could not rename group')
  }
}
async function deleteGroup(id: number, name: string) {
  if (!confirm(`Delete group "${name}"? Contacts are kept, only the group is removed.`)) return
  await store.removeGroup(id)
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
  <div class="flex h-full overflow-hidden">
    <!-- Left: groups rail -->
    <aside class="shrink-0 border-r border-border bg-surface flex flex-col" :style="{ width: groupsWidth + 'px' }">
      <div class="px-3 py-2.5 border-b border-border flex items-center justify-between">
        <span class="text-[11px] font-semibold uppercase tracking-wide text-text-muted">Contacts</span>
        <button @click="addGroup" class="p-1 rounded hover:bg-surface-hover text-accent cursor-pointer" title="Add group">
          <Plus :size="13" />
        </button>
      </div>
      <div class="flex-1 overflow-y-auto py-1.5 px-2 space-y-0.5">
        <!-- All -->
        <button @click="store.selectGroup(null)"
          class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[12px] transition-colors cursor-pointer"
          :class="store.activeGroupId === null && !store.favoritesOnly ? 'bg-accent/15 text-text-primary font-medium' : 'text-text-secondary hover:bg-surface-hover'">
          <Users :size="13" /> All contacts
        </button>
        <!-- Favorites -->
        <button @click="store.toggleFavoritesView()"
          class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[12px] transition-colors cursor-pointer"
          :class="store.favoritesOnly ? 'bg-accent/15 text-text-primary font-medium' : 'text-text-secondary hover:bg-surface-hover'">
          <Star :size="13" :class="store.favoritesOnly ? 'text-yellow-500' : ''" :fill="store.favoritesOnly ? 'currentColor' : 'none'" />
          Favorites
        </button>

        <div v-if="store.groups.length" class="pt-2">
          <div class="px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wide text-text-muted">Groups</div>
          <div v-for="g in store.groups" :key="g.id"
            class="group w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[12px] transition-colors cursor-pointer"
            :class="store.activeGroupId === g.id ? 'bg-accent/15 text-text-primary font-medium' : 'text-text-secondary hover:bg-surface-hover'"
            @click="store.selectGroup(g.id)">
            <span class="w-2 h-2 rounded-full shrink-0" :style="{ background: g.color || 'var(--color-accent)' }"></span>
            <span class="flex-1 truncate text-left">{{ g.name }}</span>
            <span class="text-[10px] text-text-muted">{{ g.member_count }}</span>
            <span class="hidden group-hover:flex items-center gap-0.5">
              <button @click.stop="renameGroup(g.id, g.name)" class="p-0.5 hover:text-accent" title="Rename"><Pencil :size="10" /></button>
              <button @click.stop="deleteGroup(g.id, g.name)" class="p-0.5 hover:text-danger" title="Delete"><X :size="11" /></button>
            </span>
          </div>
        </div>
      </div>
    </aside>

    <PanelSplitter v-model="groupsWidth" :min="168" :max="340" side="left" />

    <!-- Center: list -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Toolbar -->
      <div class="px-4 py-3 border-b border-border flex items-center gap-2">
        <div class="relative flex-1">
          <Search :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input v-model="store.search" @input="onSearchInput" placeholder="Search contacts…"
            class="w-full pl-9 pr-3 py-1.5 bg-surface-hover border border-border rounded-md text-[13px] text-text-primary outline-none focus:border-accent transition-colors" />
        </div>
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

      <!-- Empty / loading -->
      <div v-if="store.loading" class="flex-1 flex items-center justify-center text-text-muted text-[13px]">Loading contacts…</div>
      <div v-else-if="!store.contacts.length" class="flex-1 flex flex-col items-center justify-center text-center px-6">
        <div class="w-14 h-14 rounded-2xl bg-accent/10 flex items-center justify-center mb-3">
          <Users :size="24" class="text-accent/70" />
        </div>
        <h3 class="text-[14px] font-medium text-text-primary">No contacts here</h3>
        <p class="text-[12px] text-text-secondary mt-1 max-w-xs">Add contacts manually, import a .vcf file, or they'll be collected automatically from your email.</p>
        <button @click="openCreate"
          class="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white text-[12px] font-medium rounded-md hover:bg-accent-hover transition-colors cursor-pointer">
          <Plus :size="14" /> Add your first contact
        </button>
      </div>

      <!-- Letter bar + grouped list (virtualized: only visible rows render) -->
      <div v-else class="flex-1 flex overflow-hidden">
        <div ref="listScrollEl" class="flex-1 overflow-y-auto px-4 py-2">
          <div :style="{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }">
            <div v-for="vr in virtualizer.getVirtualItems()" :key="String(vr.key)"
              :style="{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${vr.start}px)` }">
              <div v-if="flat[vr.index].kind === 'header'"
                class="bg-surface py-1 text-[11px] font-bold text-text-muted tracking-wide">
                {{ flat[vr.index].letter }}
              </div>
              <button v-else @click="selectContact(flat[vr.index].contact!)"
                class="group w-full flex items-center gap-3 px-2.5 py-1.5 rounded-md transition-colors text-left cursor-pointer"
                :class="selectedId === flat[vr.index].contact!.id ? 'bg-accent/15' : 'hover:bg-surface-hover'">
                <div class="shrink-0 w-8 h-8 rounded-full overflow-hidden bg-accent/15"
                  :class="!photoFor(flat[vr.index].contact!) ? 'text-accent flex items-center justify-center text-[10px] font-bold' : ''">
                  <img v-if="photoFor(flat[vr.index].contact!)" :src="photoFor(flat[vr.index].contact!)!" :alt="flat[vr.index].contact!.name || ''" class="w-full h-full object-cover" />
                  <span v-else>{{ initials(flat[vr.index].contact!) }}</span>
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-[13px] font-medium text-text-primary truncate">{{ flat[vr.index].contact!.name || flat[vr.index].contact!.email }}</p>
                  <p class="text-[11px] text-text-secondary truncate">
                    {{ flat[vr.index].contact!.phones?.[0]?.value || flat[vr.index].contact!.email }}
                  </p>
                </div>
                <button @click.stop="store.toggleFavorite(flat[vr.index].contact!)"
                  class="p-1 rounded transition-colors shrink-0"
                  :class="flat[vr.index].contact!.is_favorite ? 'text-yellow-500' : 'text-text-muted opacity-0 group-hover:opacity-100 hover:text-yellow-500'">
                  <Star :size="14" :fill="flat[vr.index].contact!.is_favorite ? 'currentColor' : 'none'" />
                </button>
              </button>
            </div>
          </div>
        </div>

        <!-- Vertical A–Z letter bar -->
        <div class="w-6 shrink-0 flex flex-col items-center justify-start py-2 gap-0.5 border-l border-border">
          <button v-for="L in presentLetters" :key="L" @click="scrollToLetter(L)"
            class="text-[10px] font-medium text-text-muted hover:text-accent leading-none py-0.5 cursor-pointer">
            {{ L }}
          </button>
        </div>
      </div>
    </div>

    <PanelSplitter v-model="detailWidth" :min="280" :max="640" side="right" />

    <!-- Right: detail panel -->
    <div class="shrink-0 border-l border-border" :style="{ width: detailWidth + 'px' }">
      <ContactPanel :contact="selected" :groups="store.groups" @close="selectedId = null" />
    </div>

    <!-- Create slide-over -->
    <Transition name="slide">
      <div v-if="showCreateForm" class="fixed inset-0 z-40 flex justify-end">
        <div class="absolute inset-0 bg-black/30" @click="showCreateForm = false"></div>
        <div class="relative w-[480px] max-w-full bg-surface shadow-xl h-full">
          <ContactForm :contact="null" :groups="store.groups" @saved="onCreated" @cancel="showCreateForm = false" />
        </div>
      </div>
    </Transition>

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
.slide-enter-active, .slide-leave-active { transition: transform 0.25s ease; }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }

.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 10px); }
</style>
