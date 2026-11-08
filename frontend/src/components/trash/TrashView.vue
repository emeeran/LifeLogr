<script setup lang="ts">
/**
 * TrashView — soft-deleted entries awaiting the retention sweep.
 *
 * Delete is restorable: entries here keep their media until the backend's
 * daily purge (TRASH_RETENTION_DAYS, default 30). Restore puts an entry back
 * losslessly; "Delete forever" purges it immediately (confirmed — there is no
 * undo for that one).
 */
import { computed, onMounted, ref } from 'vue'
import { entriesApi } from '../../api/entries'
import { useToastStore } from '../../stores/toast'
import { errorMessage } from '../../utils/errorMessage'
import type { TrashItem } from '../../types'
import { Trash2, RotateCcw, Trash, FileText, ImageIcon, Mic, Lock } from 'lucide-vue-next'
import ConfirmDialog from '../common/ConfirmDialog.vue'

const toast = useToastStore()

const items = ref<TrashItem[]>([])
const total = ref(0)
const loading = ref(true)
const PAGE_SIZE = 50

const canLoadMore = computed(() => items.value.length < total.value)

async function load() {
  loading.value = true
  try {
    const res = await entriesApi.trash(0, PAGE_SIZE)
    items.value = res.items
    total.value = res.total
  } catch (e) {
    toast.error('Could not load trash: ' + errorMessage(e))
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  try {
    const res = await entriesApi.trash(items.value.length, PAGE_SIZE)
    items.value.push(...res.items)
    total.value = res.total
  } catch (e) {
    toast.error('Could not load more: ' + errorMessage(e))
  }
}

async function restore(item: TrashItem) {
  try {
    await entriesApi.restore(item.id)
    removeLocal(item.id)
    toast.success('Entry restored')
  } catch (e) {
    toast.error('Could not restore entry: ' + errorMessage(e))
  }
}

// "Delete forever" is irreversible — confirm before purging.
const confirmReq = ref<{ item: TrashItem } | null>(null)
async function settlePurge(ok: boolean) {
  const req = confirmReq.value
  confirmReq.value = null
  if (!ok || !req) return
  try {
    await entriesApi.purge(req.item.id)
    removeLocal(req.item.id)
    toast.success('Entry permanently deleted')
  } catch (e) {
    toast.error('Could not delete entry: ' + errorMessage(e))
  }
}

function removeLocal(id: number) {
  items.value = items.value.filter((i) => i.id !== id)
  total.value = Math.max(0, total.value - 1)
}

function relDeleted(iso: string): string {
  const days = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000))
  if (days < 1) return 'today'
  if (days === 1) return 'yesterday'
  return `${days} days ago`
}

function titleFor(item: TrashItem): string {
  if (item.title) return item.title
  if (item.is_encrypted) return 'Encrypted entry'
  return item.body_snippet.split('\n')[0].slice(0, 80) || 'Untitled entry'
}

onMounted(load)
</script>

<template>
  <div class="relative h-full overflow-y-auto px-6 py-5 space-y-5">
    <!-- Header -->
    <div class="flex items-center justify-between gap-3 flex-wrap">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
          <Trash2 :size="20" class="text-accent" />
        </div>
        <div>
          <h1 class="text-xl font-bold text-text-primary leading-tight">Trash</h1>
          <p class="text-[11px] text-text-muted mt-0.5">
            <span class="font-medium text-accent">{{ total }}</span>
            <span class="text-text-secondary"> deleted · restorable until the daily sweep purges them</span>
          </p>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && items.length === 0" class="text-center py-16 space-y-3">
      <Trash2 :size="40" class="mx-auto text-text-muted opacity-40" />
      <p class="text-text-secondary text-sm">Trash is empty</p>
      <p class="text-text-muted text-xs">
        Deleted entries rest here with their attachments until the daily sweep
        removes them.
      </p>
    </div>

    <!-- List -->
    <div v-else class="space-y-2">
      <div
        v-for="item in items"
        :key="item.id"
        class="rounded-lg border border-border bg-surface px-4 py-3 flex items-start gap-3"
      >
        <FileText :size="16" class="mt-0.5 text-text-muted shrink-0" />
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-[13px] font-medium text-text-primary truncate">
              {{ titleFor(item) }}
            </span>
            <span v-if="item.is_encrypted" class="inline-flex items-center gap-1 text-[10px] text-text-muted">
              <Lock :size="10" /> Encrypted
            </span>
          </div>
          <p v-if="!item.is_encrypted && item.body_snippet" class="text-[11px] text-text-secondary line-clamp-2 mt-0.5">
            {{ item.body_snippet }}
          </p>
          <div class="flex items-center gap-3 mt-1 text-[10px] text-text-muted flex-wrap">
            <span>{{ item.entry_date }}</span>
            <span>deleted {{ relDeleted(item.deleted_at) }}</span>
            <span v-if="item.media_count" class="inline-flex items-center gap-1">
              <ImageIcon :size="10" /> {{ item.media_count }}
            </span>
            <span v-if="item.has_recording" class="inline-flex items-center gap-1">
              <Mic :size="10" /> recording
            </span>
            <span v-for="tag in item.tags" :key="tag.id" class="text-accent">#{{ tag.name }}</span>
          </div>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <button
            title="Restore entry"
            class="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-medium rounded-md border border-border text-text-secondary hover:text-accent hover:border-accent/50 transition-colors cursor-pointer"
            @click="restore(item)"
          >
            <RotateCcw :size="12" /> Restore
          </button>
          <button
            title="Delete forever"
            class="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-medium rounded-md border border-border text-text-secondary hover:text-danger hover:border-danger/50 transition-colors cursor-pointer"
            @click="confirmReq = { item }"
          >
            <Trash :size="12" /> Delete forever
          </button>
        </div>
      </div>

      <button
        v-if="canLoadMore"
        class="w-full py-2 text-[12px] text-text-secondary hover:text-accent transition-colors cursor-pointer"
        @click="loadMore"
      >
        Load more ({{ total - items.length }} remaining)
      </button>
    </div>

    <ConfirmDialog
      v-if="confirmReq"
      title="Delete forever?"
      :message="`This permanently destroys “${titleFor(confirmReq.item)}” and its attachments. There is no undo.`"
      @confirm="settlePurge(true)"
      @cancel="settlePurge(false)"
    />
  </div>
</template>
