<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listRevisions, getRevision, diffRevisions, restoreRevision } from '../../api/revisions'
import type { RevisionResponse, RevisionDiffResponse } from '../../types'
import { History, RotateCcw, GitCompare, Loader, Eye, EyeOff } from 'lucide-vue-next'

const props = defineProps<{ entryId: number }>()
const emit = defineEmits<{ restored: [] }>()

const revisions = ref<RevisionResponse[]>([])
const diff = ref<RevisionDiffResponse | null>(null)
const loading = ref(false)
const restoring = ref(false)
const viewingRev = ref<number | null>(null)
const viewingBody = ref<string | null>(null)
const viewingLoading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const res = await listRevisions(props.entryId)
    revisions.value = res.items
  } finally {
    loading.value = false
  }
})

async function showDiff(fromRev: number, toRev: number) {
  diff.value = await diffRevisions(props.entryId, fromRev, toRev)
}

async function restore(revNumber: number) {
  restoring.value = true
  try {
    await restoreRevision(props.entryId, revNumber)
    emit('restored')
  } finally {
    restoring.value = false
  }
}

async function viewRevision(revNumber: number) {
  if (viewingRev.value === revNumber) {
    viewingRev.value = null
    viewingBody.value = null
    return
  }
  viewingRev.value = revNumber
  viewingLoading.value = true
  try {
    const rev = await getRevision(props.entryId, revNumber)
    viewingBody.value = rev.body
  } catch {
    viewingBody.value = null
    viewingRev.value = null
  } finally {
    viewingLoading.value = false
  }
}
</script>

<template>
  <div class="border border-border rounded-lg bg-surface p-3 space-y-3 text-sm">
    <span class="font-medium text-text-primary flex items-center gap-1"><History :size="14" /> Version History</span>

    <div v-if="loading" class="text-text-secondary text-xs">Loading...</div>
    <div v-else-if="revisions.length === 0" class="text-text-secondary text-xs">No revisions yet.</div>
    <div v-else class="space-y-2 max-h-60 overflow-y-auto">
      <div v-for="r in revisions" :key="r.id" class="space-y-1">
        <div class="flex items-center justify-between p-2 bg-surface-hover rounded">
          <div>
            <div class="text-xs font-medium text-text-primary">Rev #{{ r.revision_number }}</div>
            <div class="text-xs text-text-secondary">{{ r.snapshot_reason }} · {{ new Date(r.created_at).toLocaleString() }}</div>
          </div>
          <div class="flex gap-1">
            <button @click="viewRevision(r.revision_number)"
              class="p-1 rounded hover:bg-border text-text-secondary" title="View revision content">
              <Loader v-if="viewingLoading && viewingRev === r.revision_number" :size="12" class="animate-spin" />
              <EyeOff v-else-if="viewingRev === r.revision_number" :size="12" />
              <Eye v-else :size="12" />
            </button>
            <button v-if="r.revision_number < revisions[0]?.revision_number"
              @click="showDiff(r.revision_number, revisions[0].revision_number)"
              class="p-1 rounded hover:bg-border text-text-secondary" title="Compare with latest">
              <GitCompare :size="12" />
            </button>
            <button @click="restore(r.revision_number)" :disabled="restoring"
              class="p-1 rounded hover:bg-accent/10 text-accent disabled:opacity-50" title="Restore this version">
              <Loader v-if="restoring" :size="12" class="animate-spin" />
              <RotateCcw v-else :size="12" />
            </button>
          </div>
        </div>
        <!-- View revision body -->
        <div v-if="viewingRev === r.revision_number && viewingBody !== null"
          class="bg-black/20 rounded p-2 text-xs text-text-primary max-h-32 overflow-y-auto whitespace-pre-wrap font-mono">
          {{ viewingBody }}
        </div>
      </div>
    </div>

    <!-- Diff View -->
    <div v-if="diff" class="border border-border rounded p-2 space-y-2 text-xs">
      <div class="text-text-secondary">Diff: Rev #{{ diff.from_revision }} → #{{ diff.to_revision }}</div>
      <div v-if="diff.title_changed" class="space-y-1">
        <div class="text-red-400 line-through">{{ diff.from_title }}</div>
        <div class="text-green-400">{{ diff.to_title }}</div>
      </div>
    </div>
  </div>
</template>
