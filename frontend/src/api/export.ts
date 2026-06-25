import { API_ORIGIN } from './client'

const BASE_URL = `${API_ORIGIN}/api/v1`

export async function exportHtml(startDate?: string, endDate?: string): Promise<string> {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  const res = await fetch(`${BASE_URL}/export/html${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`Export HTML failed: ${res.status}`)
  return res.text()
}

export function getExportPdfUrl(startDate?: string, endDate?: string): string {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  return `${BASE_URL}/export/pdf${qs ? `?${qs}` : ''}`
}

export function getExportDiariumUrl(startDate?: string, endDate?: string): string {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  return `${BASE_URL}/entries/export/diarium${qs ? `?${qs}` : ''}`
}

export function getExportDiariumDbUrl(startDate?: string, endDate?: string): string {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  return `${BASE_URL}/entries/export/diarium-db${qs ? `?${qs}` : ''}`
}

export async function exportDiarium(startDate?: string, endDate?: string): Promise<string> {
  const params = new URLSearchParams()
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  const qs = params.toString()
  const res = await fetch(`${BASE_URL}/entries/export/diarium${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`Diarium export failed: ${res.status}`)
  return res.text()
}
