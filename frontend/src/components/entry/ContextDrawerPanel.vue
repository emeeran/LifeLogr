<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { Camera, CalendarDays, FolderOpen, FileText, Plus, AlertTriangle } from 'lucide-vue-next'
import { contextApi, type CalendarEvent, type ContextPhoto } from '../../api/context'
import { mediaApi } from '../../api/media'
import { pickFolder } from '../../utils/fileDialog'
import { isTauri } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import { formatFileSize } from '../../composables/useFormat'

/**
 * ContextDrawerPanel — the composer's local context sidebar (opt-in).
 *
 * Photos: a user-chosen directory listed by file date; attaching goes through
 * the normal media pipeline (POST /media/from-path re-validates the path).
 * Calendar: a user-chosen .ics file, read-only; "add to entry" inserts
 * formatted text at the cursor. Both paths live only in localStorage — the
 * backend receives them per request and persists nothing.
 */
const props = defineProps<{
  entryDate: string
  entryId: number | null
}>()

const emit = defineEmits<{
  /** Calendar "add to entry" — the drawer host inserts the text into the editor. */
  insertText: [text: string]
  refreshAttachments: []
}>()

const toast = useToastStore()

const photosDir = useLocalStorage<string>('lifelogr-context-photos-dir', '')
const icsPath = useLocalStorage<string>('lifelogr-context-ics-path', '')

const tab = ref<'photos' | 'calendar'>('photos')
const photos = ref<ContextPhoto[]>([])
const photosTruncated = ref(false)
const photosLoading = ref(false)
const photosError = ref('')
const events = ref<CalendarEvent[]>([])
const calendarWarnings = ref<string[]>([])
const calendarLoading = ref(false)
const calendarError = ref('')
const attachingPath = ref<string | null>(null)

// Re-open with previously chosen sources: fetch immediately (desktop only).
onMounted(() => {
  if (!isTauri) return
  if (photosDir.value) void loadPhotos()
  if (icsPath.value) void loadCalendar()
})

/** Photos on the entry's day first, then the rest (newest first). */
const sortedPhotos = computed(() => {
  const day = props.entryDate
  const onDay = photos.value.filter((p) => p.taken_date === day)
  const rest = photos.value.filter((p) => p.taken_date !== day)
  return { onDay, rest }
})

const groupedRest = computed(() => {
  const groups = new Map<string, ContextPhoto[]>()
  for (const p of sortedPhotos.value.rest) {
    const list = groups.get(p.taken_date) ?? []
    list.push(p)
    groups.set(p.taken_date, list)
  }
  return [...groups.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1))
})

async function browsePhotosDir() {
  const dir = await pickFolder()
  if (dir) {
    photosDir.value = dir
    await loadPhotos()
  }
}

/** Native .ics picker returning the path (pickFile hands back bytes only). */
async function pickIcsPath(): Promise<string | null> {
  if (!isTauri) return null
  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({
    multiple: false,
    filters: [{ name: 'iCalendar', extensions: ['ics'] }],
  })
  if (!selected || Array.isArray(selected)) return null
  return selected
}

async function browseIcsFile() {
  const path = await pickIcsPath()
  if (path) {
    icsPath.value = path
    await loadCalendar()
  }
}

async function loadPhotos() {
  if (!photosDir.value) return
  photosLoading.value = true
  photosError.value = ''
  try {
    const listing = await contextApi.listPhotos(photosDir.value)
    photos.value = listing.items
    photosTruncated.value = listing.truncated
  } catch (e: unknown) {
    photosError.value = e instanceof Error ? e.message : String(e)
  } finally {
    photosLoading.value = false
  }
}

async function loadCalendar() {
  if (!icsPath.value) return
  calendarLoading.value = true
  calendarError.value = ''
  try {
    const listing = await contextApi.listCalendar(
      icsPath.value,
      props.entryDate || undefined,
    )
    events.value = listing.items
    calendarWarnings.value = listing.warnings
  } catch (e: unknown) {
    calendarError.value = e instanceof Error ? e.message : String(e)
  } finally {
    calendarLoading.value = false
  }
}

async function attachPhoto(photo: ContextPhoto) {
  if (props.entryId === null) {
    toast.error('No entry to attach to.')
    return
  }
  attachingPath.value = photo.path
  try {
    await mediaApi.uploadFromPath(props.entryId, photo.path)
    toast.success(`${photo.filename} attached`)
    emit('refreshAttachments')
  } catch (e: unknown) {
    toast.error(`Attach failed: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    attachingPath.value = null
  }
}

function eventTime(event: CalendarEvent): string {
  if (event.all_day) return 'all day'
  return event.start.slice(11, 16)
}

function addToEntry(event: CalendarEvent) {
  const bits = [event.summary]
  const time = eventTime(event)
  if (time && time !== 'all day') bits.push(time)
  if (event.location) bits.push(event.location)
  emit('insertText', `[${bits.join(' — ')}]`)
  toast.success('Event inserted into entry')
}
</script>

<template>
  <div class="p-3 flex flex-col gap-2 text-xs">
    <!-- Tabs -->
    <div class="flex gap-1 mb-1">
      <button
        class="flex-1 px-2 py-1 rounded cursor-pointer text-[11px] font-medium"
        :class="tab === 'photos' ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:bg-surface-hover'"
        @click="tab = 'photos'"
      >
        <Camera :size="11" class="inline mr-1" /> Photos
      </button>
      <button
        class="flex-1 px-2 py-1 rounded cursor-pointer text-[11px] font-medium"
        :class="tab === 'calendar' ? 'bg-accent/20 text-accent' : 'text-text-secondary hover:bg-surface-hover'"
        @click="tab = 'calendar'"
      >
        <CalendarDays :size="11" class="inline mr-1" /> Calendar
      </button>
    </div>

    <div v-if="!isTauri" class="text-[11px] text-text-muted text-center py-3">
      The context sidebar needs the desktop app (local folder access).
    </div>

    <!-- Photos tab -->
    <template v-if="tab === 'photos' && isTauri">
      <div class="flex items-center gap-1.5">
        <button
          class="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover cursor-pointer"
          @click="browsePhotosDir"
        >
          <FolderOpen :size="11" /> {{ photosDir ? 'Change folder' : 'Pick photo folder' }}
        </button>
        <span v-if="photosDir" class="text-[10px] text-text-muted truncate" :title="photosDir">{{
          photosDir
        }}</span>
      </div>
      <p v-if="photosError" class="flex items-center gap-1 text-red-400">
        <AlertTriangle :size="10" /> {{ photosError }}
      </p>
      <template v-if="photosDir">
        <p
          v-if="sortedPhotos.onDay.length"
          class="text-[10px] uppercase tracking-wide text-text-muted mt-1"
        >
          On {{ entryDate }}
        </p>
        <div
          v-for="photo in sortedPhotos.onDay"
          :key="photo.path"
          class="flex items-center gap-2 px-2 py-1.5 rounded bg-accent/10 hover:bg-accent/20 cursor-pointer"
          @click="attachPhoto(photo)"
        >
          <Camera :size="12" class="text-text-secondary shrink-0" />
          <span class="flex-1 truncate" :title="photo.filename">{{ photo.filename }}</span>
          <span class="text-[10px] text-text-muted">{{ formatFileSize(photo.size) }}</span>
          <Plus
            v-if="attachingPath !== photo.path"
            :size="11"
            class="text-text-muted"
          />
          <span v-else class="text-[10px] text-text-muted">…</span>
        </div>
        <template v-for="([day, dayPhotos]) in groupedRest" :key="day">
          <p class="text-[10px] uppercase tracking-wide text-text-muted mt-2">{{ day }}</p>
          <div
            v-for="photo in dayPhotos"
            :key="photo.path"
            class="flex items-center gap-2 px-2 py-1.5 rounded bg-surface-hover hover:bg-surface-hover/80 cursor-pointer"
            @click="attachPhoto(photo)"
          >
            <Camera :size="12" class="text-text-muted shrink-0" />
            <span class="flex-1 truncate" :title="photo.filename">{{ photo.filename }}</span>
            <Plus :size="11" class="text-text-muted" />
          </div>
        </template>
        <p v-if="!photos.length && !photosLoading" class="text-text-muted text-center py-2">
          No photos found in that folder.
        </p>
        <p v-if="photosTruncated" class="text-[10px] text-text-muted">
          Showing the newest 200 — older files not listed.
        </p>
      </template>
    </template>

    <!-- Calendar tab -->
    <template v-if="tab === 'calendar' && isTauri">
      <div class="flex items-center gap-1.5">
        <button
          class="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover cursor-pointer"
          @click="browseIcsFile"
        >
          <FileText :size="11" /> {{ icsPath ? 'Change calendar' : 'Pick .ics file' }}
        </button>
        <span v-if="icsPath" class="text-[10px] text-text-muted truncate" :title="icsPath">{{
          icsPath
        }}</span>
      </div>
      <p v-if="calendarError" class="flex items-center gap-1 text-red-400">
        <AlertTriangle :size="10" /> {{ calendarError }}
      </p>
      <p
        v-for="warning in calendarWarnings"
        :key="warning"
        class="text-[10px] text-amber-400"
      >
        {{ warning }}
      </p>
      <template v-if="icsPath">
        <div
          v-for="(event, idx) in events"
          :key="event.uid ?? idx"
          class="px-2 py-1.5 rounded bg-surface-hover hover:bg-surface-hover/80 cursor-pointer"
          :title="event.description ?? ''"
          @click="addToEntry(event)"
        >
          <div class="flex items-center gap-1.5">
            <span class="flex-1 truncate text-text-primary">{{ event.summary }}</span>
            <span class="text-[10px] text-text-muted">{{ eventTime(event) }}</span>
            <Plus :size="11" class="text-text-muted" />
          </div>
          <p v-if="event.location" class="text-[10px] text-text-muted truncate">
            {{ event.location }}
          </p>
        </div>
        <p
          v-if="!events.length && !calendarLoading"
          class="text-text-muted text-center py-2"
        >
          No events on {{ entryDate }}.
        </p>
      </template>
    </template>
  </div>
</template>
