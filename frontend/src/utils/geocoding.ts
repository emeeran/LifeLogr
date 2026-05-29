/**
 * Reverse-geocode coordinates using Nominatim.
 * Returns "City, Country" or empty string on failure.
 */

interface NominatimReverseAddress {
  city?: string
  town?: string
  village?: string
  country?: string
}

interface NominatimReverseResult {
  address?: NominatimReverseAddress
}

export async function reverseGeocode(lat: number, lon: number): Promise<string> {
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&zoom=10`
    )
    const data: NominatimReverseResult = await res.json()
    return [
      data.address?.city || data.address?.town || data.address?.village,
      data.address?.country,
    ]
      .filter(Boolean)
      .join(', ')
  } catch {
    return ''
  }
}

interface NominatimSearchResult {
  lat: string
  lon: string
  display_name: string
}

export interface GeocodeResult {
  lat: number
  lon: number
  display_name: string
}

/**
 * Forward-geocode a place name using Nominatim search.
 * Returns up to 5 matching results.
 */
export async function forwardGeocode(query: string): Promise<GeocodeResult[]> {
  if (!query.trim()) return []
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=5`
    )
    const data: NominatimSearchResult[] = await res.json()
    return data.map((r) => ({
      lat: parseFloat(r.lat),
      lon: parseFloat(r.lon),
      display_name: r.display_name,
    }))
  } catch {
    return []
  }
}
