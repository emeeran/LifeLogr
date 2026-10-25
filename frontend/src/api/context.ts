import { request } from './client'

/** Composer context sidebar — local photos + ICS calendar, read-only.
 *  Paths are sent per request; the backend persists nothing. */

export interface ContextPhoto {
  path: string
  filename: string
  size: number
  /** File mtime date (YYYY-MM-DD) — EXIF capture date is a future item. */
  taken_date: string
  media_type: string
}

export interface PhotoListing {
  items: ContextPhoto[]
  scanned: number
  truncated: boolean
}

export interface CalendarEvent {
  uid: string | null
  summary: string
  start: string
  end: string | null
  all_day: boolean
  location: string | null
  description: string | null
}

export interface CalendarListing {
  items: CalendarEvent[]
  source: string
  warnings: string[]
}

export const contextApi = {
  listPhotos(path: string, date?: string, limit = 200): Promise<PhotoListing> {
    return request('/context/photos', {
      method: 'POST',
      body: JSON.stringify({ path, date, limit }),
    })
  },

  listCalendar(
    path: string,
    startDate?: string,
    endDate?: string,
    limit = 200,
  ): Promise<CalendarListing> {
    return request('/context/calendar', {
      method: 'POST',
      body: JSON.stringify({
        path,
        start_date: startDate,
        end_date: endDate,
        limit,
      }),
    })
  },
}
