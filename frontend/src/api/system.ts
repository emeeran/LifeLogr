import { request } from './client'

export type IntegrityStatus = 'ok' | 'warn' | 'error'

export interface IntegrityCheck {
  id: string
  label: string
  status: IntegrityStatus
  detail: string
  hint?: string
}

export interface IntegritySummary {
  ok: number
  warn: number
  error: number
}

export interface IntegrityReport {
  ran: boolean
  ran_at: string | null
  checks: IntegrityCheck[]
  summary: IntegritySummary
}

export function getIntegrity(): Promise<IntegrityReport> {
  return request<IntegrityReport>('/system/integrity')
}

export function refreshIntegrity(): Promise<IntegrityReport> {
  return request<IntegrityReport>('/system/integrity', { method: 'POST' })
}

export function rebuildSearchIndex(): Promise<IntegrityReport> {
  return request<IntegrityReport>('/system/integrity/rebuild-search-index', {
    method: 'POST',
  })
}
