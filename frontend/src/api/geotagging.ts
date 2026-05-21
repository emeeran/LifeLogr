import { request } from './client'
import type { GeotagResponse, NearbyEntry, GeotagUpdate } from '../types'

export const setGeotag = (entryId: number, data: GeotagUpdate) =>
  request<GeotagResponse>(`/entries/${entryId}/geotag`, { method: 'PUT', body: JSON.stringify(data) })

export const removeGeotag = (entryId: number) =>
  request<void>(`/entries/${entryId}/geotag`, { method: 'DELETE' })

export const mapView = () =>
  request<GeotagResponse[]>('/entries/map')

export const nearbyEntries = (lat: number, lon: number, radiusKm: number = 10, limit: number = 20) =>
  request<{ items: NearbyEntry[]; total: number }>(`/entries/nearby?lat=${lat}&lon=${lon}&radius_km=${radiusKm}&limit=${limit}`)
