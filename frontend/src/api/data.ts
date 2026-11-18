/** Egress URL builders + text fetchers for the Data tab's export operations.
 *  Bulk/media imports stay in `api/backup.ts` (archive) and `api/entries.ts`
 *  / `api/notes.ts` (multipart uploads) — they are request wrappers, not URLs.
 */
import { API_ORIGIN, textRequest } from './client'

const BASE_URL = `${API_ORIGIN}/api/v1`

export async function exportHtml(
  startDate?: string,
  endDate?: string,
): Promise<string> {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  return textRequest(`/export/html${qs ? `?${qs}` : ''}`)
}

export function getExportPdfUrl(startDate?: string, endDate?: string): string {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  return `${BASE_URL}/export/pdf${qs ? `?${qs}` : ''}`
}

export function getExportDiariumDbUrl(
  startDate?: string,
  endDate?: string,
): string {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  return `${BASE_URL}/entries/export/diarium-db${qs ? `?${qs}` : ''}`
}

export async function exportDiarium(
  startDate?: string,
  endDate?: string,
): Promise<string> {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  return textRequest(`/entries/export/diarium${qs ? `?${qs}` : ''}`)
}

/** Full-instance local backup archive (.tar.gz, DB + media). */
export function getBackupArchiveUrl(): string {
  return `${BASE_URL}/backup/export`
}
