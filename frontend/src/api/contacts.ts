import { request, API_ORIGIN } from './client'
import type { ContactResponse, ContactCreate, ContactUpdate, ContactListResponse } from '../types'

const BASE = '/contacts'

export const listContacts = (params?: { search?: string; offset?: number; limit?: number }) => {
  const qs = new URLSearchParams()
  if (params?.search) qs.set('search', params.search)
  if (params?.offset != null) qs.set('offset', String(params.offset))
  if (params?.limit != null) qs.set('limit', String(params.limit))
  const tail = qs.toString()
  return request<ContactListResponse>(tail ? `${BASE}?${tail}` : BASE)
}

export const getContact = (id: number) => request<ContactResponse>(`${BASE}/${id}`)

export const createContact = (data: ContactCreate) =>
  request<ContactResponse>(BASE, { method: 'POST', body: JSON.stringify(data) })

export const updateContact = (id: number, data: ContactUpdate) =>
  request<ContactResponse>(`${BASE}/${id}`, { method: 'PATCH', body: JSON.stringify(data) })

export const deleteContact = (id: number) =>
  request<void>(`${BASE}/${id}`, { method: 'DELETE' })

export const restoreContact = (id: number) =>
  request<ContactResponse>(`${BASE}/${id}/restore`, { method: 'POST' })

/** Trigger a .vcf download of all (or selected) contacts. */
export async function exportContacts(ids?: number[]): Promise<void> {
  const qs = new URLSearchParams()
  if (ids?.length) qs.set('ids', ids.join(','))
  const tail = qs.toString()
  const res = await fetch(`${API_ORIGIN}/api/v1${BASE}/export${tail ? `?${tail}` : ''}`)
  if (!res.ok) throw new Error(`Export failed: ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'contacts.vcf'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const importContacts = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return request<{ imported: number }>(`${BASE}/import`, { method: 'POST', body: fd })
}
