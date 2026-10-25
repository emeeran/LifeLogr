<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as L from 'leaflet'
import 'leaflet.markercluster'
import 'leaflet/dist/leaflet.css'
import 'leaflet.markercluster/dist/MarkerCluster.css'
import 'leaflet.markercluster/dist/MarkerCluster.Default.css'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'
import { entriesApi, type GeotagItem } from '../../api/entries'
import { getSettings } from '../../api/settings'
import { API_ORIGIN } from '../../api/client'
import { useUiStore } from '../../stores/ui'
import { MapPin } from 'lucide-vue-next'

/**
 * MapView — every geotagged entry on a map.
 *
 * Privacy (see the egress report's `map_tiles` row): the map is **plot-only
 * by default** — no tile layer is created, so no request leaves the device.
 * Online OpenStreetMap basemap tiles render only when the user opts in via
 * Settings → Privacy (persisted backend-side so the report stays truthful).
 */
const ui = useUiStore()

const mapEl = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const errorMsg = ref('')
const entries = ref<GeotagItem[]>([])
const onlineTiles = ref(false)

let map: L.Map | null = null
const clusterGroup = ref<L.MarkerClusterGroup | null>(null)

// Bundlers rewrite Leaflet's default icon paths; repoint them at the bundled
// assets explicitly.
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
})

function popupHtml(entry: GeotagItem): string {
  const title = entry.title ?? entry.location_name ?? 'Journal entry'
  const media = entry.media_id
    ? `<img src="${API_ORIGIN}/api/v1/media/${entry.media_id}/file" alt="" style="max-width:160px;border-radius:4px;margin-bottom:4px" /><br/>`
    : ''
  return (
    `${media}<strong>${escapeHtml(title)}</strong><br/>` +
    `<span style="color:#666">${entry.entry_date}</span><br/>` +
    `<a href="#" data-entry-id="${entry.id}" style="color:#3498db">Open entry</a>`
  )
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}

function openEntry(entryId: number) {
  // Same open flow as the calendar's day cards.
  ui.requestEdit(entryId)
}

function renderMarkers() {
  if (!map) return
  clusterGroup.value?.remove()
  const group = L.markerClusterGroup()
  for (const entry of entries.value) {
    const marker = L.marker([entry.latitude, entry.longitude], { title: entry.title ?? '' })
    marker.bindPopup(popupHtml(entry))
    group.addLayer(marker)
  }
  group.on('click', (e) => {
    const target = e.originalEvent?.target as HTMLElement | null
    const link = target?.closest?.('a[data-entry-id]')
    if (link) {
      e.originalEvent?.preventDefault()
      openEntry(Number((link as HTMLElement).dataset.entryId))
    }
  })
  clusterGroup.value = group
  map.addLayer(group)

  const bounds = group.getBounds()
  if (bounds.isValid()) {
    map.fitBounds(bounds.pad(0.15), { maxZoom: 15 })
  }
}

onMounted(async () => {
  try {
    const [settings, first] = await Promise.all([
      getSettings(),
      entriesApi.geotags(0, 500),
    ])
    onlineTiles.value = settings.map.online_tiles

    if (!mapEl.value) return
    map = L.map(mapEl.value, { center: [20, 0], zoom: 2 })
    if (onlineTiles.value) {
      // The ONLY network surface of this view — behind the explicit opt-in.
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors',
      }).addTo(map)
    }

    const all = [...first.items]
    // Page through the remainder (500 at a time, hard cap 10k).
    let offset = first.items.length
    while (offset < Math.min(first.total, 10_000)) {
      const page = await entriesApi.geotags(offset, 500)
      all.push(...page.items)
      offset += page.items.length
      if (!page.items.length) break
    }
    entries.value = all
    renderMarkers()
  } catch (e: unknown) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div class="h-full flex flex-col">
    <div
      class="flex items-center justify-between px-4 py-2 border-b border-border"
    >
      <h1 class="text-sm font-medium text-text-primary flex items-center gap-1.5">
        <MapPin :size="15" /> Map
        <span v-if="!loading" class="text-xs font-normal text-text-muted"
          >· {{ entries.length }} geotagged {{ entries.length === 1 ? 'entry' : 'entries' }}</span
        >
      </h1>
      <span v-if="!onlineTiles" class="text-[10px] text-text-muted">
        plot-only · basemap off (Settings → Privacy to enable tiles)
      </span>
    </div>
    <div class="relative flex-1 min-h-0">
      <div v-if="loading" class="absolute inset-0 flex items-center justify-center text-xs text-text-muted">
        Loading places…
      </div>
      <div v-else-if="errorMsg" class="absolute inset-0 flex items-center justify-center text-xs text-red-400">
        {{ errorMsg }}
      </div>
      <div
        v-else-if="!entries.length"
        class="absolute inset-0 flex flex-col items-center justify-center gap-1 text-text-muted"
      >
        <MapPin :size="22" />
        <p class="text-xs">No geotagged entries yet — add coordinates to an entry.</p>
      </div>
      <!-- Plot-only: Leaflet with no tile layer makes zero network requests.
           The .map-plot class paints the basemap replacement background. -->
      <div ref="mapEl" class="map-plot h-full w-full" />
    </div>
  </div>
</template>

<style scoped>
.map-plot {
  background: var(--color-surface, #1a1a2e);
  z-index: 0;
}
.map-plot :deep(.leaflet-popup-content-wrapper) {
  color: #222;
}
</style>
