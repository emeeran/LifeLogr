<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { setGeotag, removeGeotag } from '../../api/geotagging'
import { reverseGeocode, forwardGeocode, type GeocodeResult } from '../../utils/geocoding'
import { MapPin, X, Search, Check } from 'lucide-vue-next'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

// Custom marker icon (avoids Leaflet's broken default icon in bundled apps)
const pinIcon = L.divIcon({
  className: '',
  html: `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="40" viewBox="0 0 28 40">
    <path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.27 21.73 0 14 0z" fill="#6366f1" stroke="#fff" stroke-width="2"/>
    <circle cx="14" cy="14" r="6" fill="#fff"/>
  </svg>`,
  iconSize: [28, 40],
  iconAnchor: [14, 40],
})

const props = defineProps<{ entryId: number; lat?: number | null; lon?: number | null; name?: string | null }>()
const emit = defineEmits<{ close: []; saved: []; pending: [data: { latitude: number; longitude: number; location_name: string | null }] }>()

const latVal = ref(props.lat ?? null)
const lonVal = ref(props.lon ?? null)
const nameVal = ref(props.name || '')
const loading = ref(false)
const selected = ref(false) // tracks whether user has picked a location

// Map state
const mapContainer = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let marker: L.Marker | null = null

// Search state
const searchQuery = ref('')
const searchResults = ref<GeocodeResult[]>([])
const searching = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

// Updating flag to prevent circular updates between fields and map
let updatingFromMap = false

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  map?.remove()
  map = null
})

function initMap() {
  if (!mapContainer.value) return

  const hasCoords = latVal.value != null && lonVal.value != null
  if (hasCoords) selected.value = true
  const center: L.LatLngExpression = hasCoords
    ? [latVal.value!, lonVal.value!]
    : [20, 0] // Default: world view
  const zoom = hasCoords ? 13 : 2

  map = L.map(mapContainer.value, {
    center,
    zoom,
    zoomControl: false,
  })

  L.control.zoom({ position: 'topright' }).addTo(map)

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
    maxZoom: 19,
  }).addTo(map)

  if (hasCoords) {
    placeMarker(latVal.value!, lonVal.value!)
  }

  // Click to place marker
  map.on('click', (e: L.LeafletMouseEvent) => {
    const { lat, lng } = e.latlng
    placeMarker(lat, lng)
    updateFromMap(lat, lng)
  })

  // Force invalidateSize after DOM is ready
  setTimeout(() => map?.invalidateSize(), 100)
}

function placeMarker(lat: number, lon: number) {
  if (marker) {
    marker.setLatLng([lat, lon])
  } else {
    marker = L.marker([lat, lon], { draggable: true, icon: pinIcon }).addTo(map!)
    marker.on('dragend', () => {
      const pos = marker!.getLatLng()
      updateFromMap(pos.lat, pos.lng)
    })
  }
}

async function updateFromMap(lat: number, lon: number) {
  updatingFromMap = true
  latVal.value = Math.round(lat * 1000000) / 1000000
  lonVal.value = Math.round(lon * 1000000) / 1000000
  selected.value = true
  // Reverse geocode for location name
  const placeName = await reverseGeocode(lat, lon)
  if (placeName) nameVal.value = placeName
  updatingFromMap = false
}

// Watch lat/lon fields for manual changes → update marker
watch([latVal, lonVal], () => {
  if (updatingFromMap) return
  if (latVal.value != null && lonVal.value != null && map) {
    placeMarker(latVal.value, lonVal.value)
    map.setView([latVal.value, lonVal.value], map.getZoom() < 10 ? 13 : map.getZoom())
    selected.value = true
  }
})

// Search with debounce
watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!q.trim()) { searchResults.value = []; return }
  searchTimer = setTimeout(async () => {
    searching.value = true
    searchResults.value = await forwardGeocode(q)
    searching.value = false
  }, 400)
})

function selectSearchResult(r: GeocodeResult) {
  latVal.value = r.lat
  lonVal.value = r.lon
  nameVal.value = r.display_name.split(',').slice(0, 2).join(',').trim()
  searchQuery.value = ''
  searchResults.value = []
  selected.value = true
  if (map) {
    placeMarker(r.lat, r.lon)
    map.setView([r.lat, r.lon], 14)
  }
}

async function save() {
  const data = {
    latitude: latVal.value!,
    longitude: lonVal.value!,
    location_name: nameVal.value || null,
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
    if (e.message?.includes('404')) {
      alert('This entry no longer exists. It may have been deleted. Please refresh and try again.')
    } else {
      alert('Failed to save location. Please try again.')
    }
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

onMounted(() => nextTick(() => initMap()))
</script>

<template>
  <div class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="emit('close')">
    <div class="bg-surface rounded-lg border border-border shadow-xl flex flex-col" style="width: 640px; max-height: 90vh; overflow-y: auto;">
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <h3 class="text-sm font-semibold text-text-primary flex items-center gap-2"><MapPin :size="16" /> Set Location</h3>
        <button @click="emit('close')" class="text-text-secondary hover:text-text-primary cursor-pointer"><X :size="16" /></button>
      </div>

      <!-- Instruction -->
      <div v-if="!selected" class="px-4 py-2 bg-accent/10 text-accent text-xs text-center font-medium">
        Click on the map or search for a place to set location
      </div>
      <div v-else class="px-4 py-2 bg-green-500/10 text-green-400 text-xs text-center font-medium flex items-center justify-center gap-1">
        <Check :size="12" /> Location selected — drag pin to adjust
      </div>

      <!-- Map -->
      <div class="relative">
        <!-- Search bar overlay -->
        <div class="absolute top-2 left-2 right-2 z-[1000]">
          <div class="relative">
            <div class="flex items-center bg-surface border border-border rounded shadow-lg overflow-hidden">
              <Search :size="14" class="text-text-muted ml-2 shrink-0" />
              <input
                v-model="searchQuery"
                class="flex-1 px-2 py-1.5 bg-transparent text-sm text-text-primary outline-none placeholder:text-text-muted"
                placeholder="Search for a place..."
                @keydown.escape.stop="searchQuery = ''; searchResults = []"
              />
              <button v-if="searchQuery" @click="searchQuery = ''; searchResults = []"
                class="px-2 text-text-muted hover:text-text-primary cursor-pointer"><X :size="12" /></button>
            </div>
            <!-- Search results dropdown -->
            <div v-if="searchResults.length" class="absolute top-full left-0 right-0 mt-1 bg-surface border border-border rounded shadow-lg max-h-48 overflow-y-auto z-[1001]">
              <button
                v-for="r in searchResults"
                :key="r.display_name"
                @click="selectSearchResult(r)"
                class="w-full text-left px-3 py-2 text-xs text-text-primary hover:bg-surface-hover cursor-pointer border-b border-border last:border-b-0"
              >
                {{ r.display_name }}
              </button>
            </div>
          </div>
        </div>

        <div ref="mapContainer" class="w-full h-[280px]" />
      </div>

      <!-- Controls -->
      <div class="px-4 py-3 space-y-3 shrink-0">
        <!-- Coordinate fields -->
        <div class="grid grid-cols-3 gap-2">
          <div>
            <label class="text-[10px] text-text-secondary">Latitude</label>
            <input
              v-model.number="latVal"
              type="number"
              step="0.000001"
              placeholder="51.5074"
              class="w-full px-2 py-1 bg-surface-hover border border-border rounded text-xs text-text-primary outline-none focus:border-accent"
            />
          </div>
          <div>
            <label class="text-[10px] text-text-secondary">Longitude</label>
            <input
              v-model.number="lonVal"
              type="number"
              step="0.000001"
              placeholder="-0.1278"
              class="w-full px-2 py-1 bg-surface-hover border border-border rounded text-xs text-text-primary outline-none focus:border-accent"
            />
          </div>
          <div>
            <label class="text-[10px] text-text-secondary">Location Name</label>
            <input
              v-model="nameVal"
              placeholder="London, UK"
              class="w-full px-2 py-1 bg-surface-hover border border-border rounded text-xs text-text-primary outline-none focus:border-accent"
            />
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="flex gap-2 justify-end px-4 py-3 border-t border-border shrink-0">
        <button v-if="props.lat" @click="remove" :disabled="loading"
          class="px-3 py-1.5 text-sm text-red-400 hover:bg-red-500/10 rounded cursor-pointer">Remove</button>
        <div class="flex-1" />
        <button @click="emit('close')" class="px-3 py-1.5 text-sm bg-surface-hover text-text-secondary rounded hover:bg-border cursor-pointer">Cancel</button>
        <button @click="save" :disabled="loading || latVal == null || lonVal == null"
          class="px-3 py-1.5 text-sm bg-accent text-white rounded hover:bg-accent/90 disabled:opacity-50 cursor-pointer">Save Location</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
:deep(.leaflet-container) {
  font-family: inherit;
  cursor: crosshair !important;
}
:deep(.leaflet-grab) {
  cursor: crosshair !important;
}
:deep(.leaflet-dragging .leaflet-grab) {
  cursor: grabbing !important;
}
</style>
