<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { setGeotag, removeGeotag } from '../../api/geotagging'
import { reverseGeocode } from '../../utils/geocoding'
import { MapPin, X, Crosshair } from 'lucide-vue-next'

const props = defineProps<{ entryId: number; lat?: number | null; lon?: number | null; name?: string | null }>()
const emit = defineEmits<{ close: []; saved: []; pending: [data: { latitude: number; longitude: number; location_name: string | null }] }>()

const lat = ref(props.lat?.toString() || '')
const lon = ref(props.lon?.toString() || '')
const name = ref(props.name || '')
const loading = ref(false)
const detecting = ref(false)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))

async function save() {
  const data = {
    latitude: parseFloat(lat.value),
    longitude: parseFloat(lon.value),
    location_name: name.value || null,
  }
  if (props.entryId === -1) {
    emit('pending', data)
    emit('close')
    return
  }
  loading.value = true
  try {
    await setGeotag(props.entryId, data)
    emit('saved')
    emit('close')
  } catch (e: any) {
    alert(e.message)
  } finally {
    loading.value = false
  }
}

async function remove() {
  loading.value = true
  try {
    await removeGeotag(props.entryId)
    emit('saved')
    emit('close')
  } finally {
    loading.value = false
  }
}

function detectLocation() {
  if (!navigator.geolocation) {
    alert('Geolocation is not supported by your browser')
    return
  }
  detecting.value = true
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      lat.value = pos.coords.latitude.toFixed(6)
      lon.value = pos.coords.longitude.toFixed(6)
      name.value = await reverseGeocode(pos.coords.latitude, pos.coords.longitude)
      detecting.value = false
    },
    () => {
      alert('Could not detect location. Check browser permissions.')
      detecting.value = false
    },
    { enableHighAccuracy: false, timeout: 8000 }
  )
}
</script>

<template>
  <div class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="emit('close')">
    <div class="bg-surface rounded-lg border border-border p-5 w-96 space-y-4 shadow-xl">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-text-primary flex items-center gap-2"><MapPin :size="16" /> Set Location</h3>
        <button @click="emit('close')" class="text-text-secondary hover:text-text-primary"><X :size="16" /></button>
      </div>

      <div class="space-y-3">
        <button
          @click="detectLocation"
          :disabled="detecting"
          class="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-sm font-medium transition-colors cursor-pointer"
          :class="detecting ? 'bg-accent/10 text-accent/60' : 'bg-accent/15 text-accent hover:bg-accent/25'"
        >
          <Crosshair :size="14" :class="detecting ? 'animate-spin' : ''" />
          {{ detecting ? 'Detecting...' : 'Detect My Location' }}
        </button>

        <div class="flex items-center gap-2 text-[10px] text-text-muted">
          <span class="flex-1 h-px bg-border" />or enter manually<span class="flex-1 h-px bg-border" />
        </div>

        <div>
          <label class="text-xs text-text-secondary">Latitude</label>
          <input v-model="lat" type="number" step="0.0001" placeholder="51.5074"
            class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
        </div>
        <div>
          <label class="text-xs text-text-secondary">Longitude</label>
          <input v-model="lon" type="number" step="0.0001" placeholder="-0.1278"
            class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
        </div>
        <div>
          <label class="text-xs text-text-secondary">Location Name (optional)</label>
          <input v-model="name" placeholder="London, UK"
            class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
        </div>
      </div>

      <div class="flex gap-2 justify-end">
        <button v-if="props.lat" @click="remove" :disabled="loading"
          class="px-3 py-1.5 text-sm text-red-400 hover:bg-red-500/10 rounded">Remove</button>
        <div class="flex-1" />
        <button @click="emit('close')" class="px-3 py-1.5 text-sm bg-surface-hover text-text-secondary rounded hover:bg-border">Cancel</button>
        <button @click="save" :disabled="loading || !lat || !lon"
          class="px-3 py-1.5 text-sm bg-accent text-white rounded hover:bg-accent/90 disabled:opacity-50">Save</button>
      </div>
    </div>
  </div>
</template>
