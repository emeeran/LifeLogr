/**
 * Reverse-geocode coordinates using Nominatim.
 * Returns "City, Country" or empty string on failure.
 */
export async function reverseGeocode(lat: number, lon: number): Promise<string> {
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&zoom=10`
    )
    const data = await res.json()
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
