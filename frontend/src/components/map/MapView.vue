<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { mapView, nearbyEntries } from '../../api/geotagging'
import type { GeotagResponse, NearbyEntry } from '../../types'
import { MapPin, Navigation } from 'lucide-vue-next'

const geotagged = ref<GeotagResponse[]>([])
const nearby = ref<NearbyEntry[]>([])
const loading = ref(false)
const searchLat = ref('')
const searchLon = ref('')
const searchRadius = ref('10')

onMounted(async () => {
  loading.value = true
  try { geotagged.value = await mapView() }
  finally { loading.value = false }
})

async function searchNearby() {
  if (!searchLat.value || !searchLon.value) return
  loading.value = true
  try {
    const res = await nearbyEntries(
      parseFloat(searchLat.value),
      parseFloat(searchLon.value),
      parseFloat(searchRadius.value)
    )
    nearby.value = res.items
  } finally {
    loading.value = false
  }
}

function openInOSM(lat: number, lon: number) {
  window.open(`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=15/${lat}/${lon}`, '_blank')
}
</script>

<template>
  <div class="h-full overflow-y-auto p-6 space-y-6">
    <h1 class="text-2xl font-bold text-text-primary flex items-center gap-2">
      <MapPin :size="24" /> Map
    </h1>

    <!-- Search nearby -->
    <div class="bg-surface rounded-lg p-4 border border-border">
      <h2 class="text-sm font-semibold text-text-primary mb-3 flex items-center gap-2"><Navigation :size="16" /> Find Nearby Entries</h2>
      <div class="flex gap-2 items-end">
        <div>
          <label class="text-xs text-text-secondary">Latitude</label>
          <input v-model="searchLat" type="number" step="0.0001" placeholder="51.5074"
            class="w-32 px-2 py-1.5 text-sm bg-surface-hover border border-border rounded text-text-primary" />
        </div>
        <div>
          <label class="text-xs text-text-secondary">Longitude</label>
          <input v-model="searchLon" type="number" step="0.0001" placeholder="-0.1278"
            class="w-32 px-2 py-1.5 text-sm bg-surface-hover border border-border rounded text-text-primary" />
        </div>
        <div>
          <label class="text-xs text-text-secondary">Radius (km)</label>
          <input v-model="searchRadius" type="number" min="0.1" step="1"
            class="w-20 px-2 py-1.5 text-sm bg-surface-hover border border-border rounded text-text-primary" />
        </div>
        <button @click="searchNearby" :disabled="loading"
          class="px-4 py-1.5 bg-accent text-white text-sm rounded hover:bg-accent/90 disabled:opacity-50">Search</button>
      </div>
    </div>

    <!-- Nearby Results -->
    <div v-if="nearby.length" class="bg-surface rounded-lg p-4 border border-border">
      <h2 class="text-sm font-semibold text-text-primary mb-3">Nearby ({{ nearby.length }})</h2>
      <div class="space-y-2">
        <div v-for="e in nearby" :key="e.id" @click="openInOSM(e.latitude, e.longitude)"
          class="flex items-center justify-between p-3 bg-surface-hover rounded cursor-pointer hover:bg-border transition-colors">
          <div>
            <div class="text-sm font-medium text-text-primary">{{ e.title || e.entry_date }}</div>
            <div class="text-xs text-text-secondary">{{ e.entry_date }} · {{ e.distance_km }} km away</div>
            <div v-if="e.location_name" class="text-xs text-text-secondary">{{ e.location_name }}</div>
          </div>
          <MapPin :size="16" class="text-accent" />
        </div>
      </div>
    </div>

    <!-- All Geotagged Entries -->
    <div class="bg-surface rounded-lg p-4 border border-border">
      <h2 class="text-sm font-semibold text-text-primary mb-3">Geotagged Entries ({{ geotagged.length }})</h2>
      <div v-if="geotagged.length === 0" class="text-sm text-text-secondary py-4 text-center">
        No geotagged entries yet. Set a location on an entry to see it here.
      </div>
      <div v-else class="space-y-2">
        <div v-for="g in geotagged" :key="g.entry_id" @click="g.latitude && g.longitude && openInOSM(g.latitude, g.longitude)"
          class="flex items-center justify-between p-3 bg-surface-hover rounded cursor-pointer hover:bg-border transition-colors">
          <div>
            <div class="text-sm font-medium text-text-primary">Entry #{{ g.entry_id }}</div>
            <div v-if="g.location_name" class="text-xs text-text-secondary">{{ g.location_name }}</div>
            <div class="text-xs text-text-secondary">{{ g.latitude?.toFixed(4) }}, {{ g.longitude?.toFixed(4) }}</div>
          </div>
          <MapPin :size="16" class="text-accent/60" />
        </div>
      </div>
    </div>
  </div>
</template>
