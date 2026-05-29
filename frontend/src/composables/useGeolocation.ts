import { type Ref } from 'vue'
import { reverseGeocode } from '../utils/geocoding'

/**
 * Composable for auto-geotagging new journal entries.
 * Extracts geotag state and auto-geotag logic from EntryEditor.
 */
export function useGeolocation(options: {
  isNew: Ref<boolean>
  autoGeotag: Ref<boolean>
  pendingGeotag: Ref<{ latitude: number; longitude: number; location_name: string | null } | null>
}) {
  function requestGeolocation() {
    if (!options.autoGeotag.value || !navigator.geolocation) return

    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude
        const lon = pos.coords.longitude
        if (options.isNew.value && !options.pendingGeotag.value) {
          try {
            const placeName = await reverseGeocode(lat, lon)
            options.pendingGeotag.value = {
              latitude: Math.round(lat * 1000000) / 1000000,
              longitude: Math.round(lon * 1000000) / 1000000,
              location_name: placeName || null,
            }
          } catch {
            options.pendingGeotag.value = {
              latitude: Math.round(lat * 1000000) / 1000000,
              longitude: Math.round(lon * 1000000) / 1000000,
              location_name: null,
            }
          }
        }
      },
      () => { /* location denied or unavailable — silently skip */ },
      { enableHighAccuracy: false, timeout: 5000 },
    )
  }

  return {
    requestGeolocation,
  }
}
