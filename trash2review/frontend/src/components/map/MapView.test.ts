import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'

/**
 * MapView — every geotagged entry on a map, plot-only by default.
 *
 * The privacy contract is enforced here: with online tiles off, **no tile
 * layer is ever created** (Leaflet only fetches tiles through a tileLayer, so
 * "never constructed" = zero tile requests). Mocking Leaflet lets us assert
 * that directly — the client-side interceptor equivalent for a mocked canvas.
 */

const h = vi.hoisted(() => ({
  onlineTiles: false,
  tileLayer: vi.fn(),
  markerClusterGroup: vi.fn(),
  map: vi.fn(),
  marker: vi.fn(),
}))

vi.mock('leaflet', () => ({
  map: (...args: unknown[]) => h.map(...(args as [])),
  tileLayer: (...args: unknown[]) => h.tileLayer(...(args as [])),
  marker: (...args: unknown[]) => h.marker(...(args as [])),
  markerClusterGroup: (...args: unknown[]) => h.markerClusterGroup(...(args as [])),
  Icon: { Default: { mergeOptions: vi.fn() } },
}))

vi.mock('leaflet.markercluster', () => ({}))

vi.mock('../../api/entries', () => ({
  entriesApi: {
    geotags: vi.fn(async () => ({
      items: [
        {
          id: 1,
          entry_date: '2026-05-01',
          title: 'Ridge hike',
          latitude: 45.5,
          longitude: -122.6,
          location_name: null,
          is_encrypted: false,
          media_id: 42,
        },
        {
          id: 2,
          entry_date: '2026-05-02',
          title: null,
          latitude: 52.52,
          longitude: 13.405,
          location_name: 'Berlin',
          is_encrypted: false,
          media_id: null,
        },
      ],
      total: 2,
      offset: 0,
      limit: 500,
    })),
  },
}))

vi.mock('../../api/settings', () => ({
  getSettings: vi.fn(async () => ({
    ai: {},
    weather: { enabled: false },
    map: { get online_tiles() { return h.onlineTiles } },
    storage: {},
    version: 'test',
    app_name: 'LifeLogr',
  })),
}))

vi.mock('../../api/client', () => ({
  API_ORIGIN: 'http://127.0.0.1:18765',
  isTauri: false,
}))

async function mountView() {
  const { default: MapView } = await import('./MapView.vue')
  const wrapper = mount(MapView, { global: { plugins: [createPinia()] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  h.onlineTiles = false
  h.tileLayer.mockClear()
  h.markerClusterGroup.mockClear()
  h.marker.mockClear()
  h.map.mockReset()
  // A minimal fake map: the component only needs addLayer/fitBounds/remove.
  h.map.mockReturnValue({
    addLayer: vi.fn(),
    fitBounds: vi.fn(),
    remove: vi.fn(),
  })
  h.markerClusterGroup.mockReturnValue({
    addLayer: vi.fn(),
    remove: vi.fn(),
    on: vi.fn(),
    // Real Leaflet's empty-cluster bounds are invalid — matches both the
    // populated and empty fixtures (fitBounds is skipped either way).
    getBounds: () => ({ isValid: () => false, pad: () => ({}) }),
  })
  h.marker.mockReturnValue({ bindPopup: vi.fn() })
  h.tileLayer.mockReturnValue({ addTo: vi.fn() })
})

describe('MapView', () => {
  it('renders markers for all geotagged entries with zero tile requests (default)', async () => {
    const wrapper = await mountView()

    // Two markers created, one cluster group, and — the acceptance criterion —
    // no tile layer constructed, so Leaflet can never fetch a tile.
    expect(h.marker).toHaveBeenCalledTimes(2)
    expect(h.markerClusterGroup).toHaveBeenCalledTimes(1)
    expect(h.tileLayer).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('2 geotagged entries')
    expect(wrapper.text()).toContain('plot-only')

    // Popup content carries the title, date, and a thumbnail reference.
    const popup = h.marker.mock.results[0].value.bindPopup.mock.calls[0][0] as string
    expect(popup).toContain('Ridge hike')
    expect(popup).toContain('2026-05-01')
    expect(popup).toContain('/api/v1/media/42/thumb')
  })

  it('creates the OSM tile layer only when the opt-in is on', async () => {
    h.onlineTiles = true
    await mountView()

    expect(h.tileLayer).toHaveBeenCalledTimes(1)
    expect(String(h.tileLayer.mock.calls[0][0])).toContain('tile.openstreetmap.org')
  })

  it('shows the empty state without geotagged entries', async () => {
    const entriesModule = await import('../../api/entries')
    vi.mocked(entriesModule.entriesApi.geotags).mockResolvedValueOnce({
      items: [],
      total: 0,
      offset: 0,
      limit: 500,
    })
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('No geotagged entries')
    expect(h.marker).not.toHaveBeenCalled()
  })
})
