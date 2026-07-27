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

// ── Egress report (Privacy tab) ──
// Every surface that can send data off the device, with whether it is active.
export interface EgressCloudAI {
  leaves_device: boolean
  active: boolean
  provider: string
  preset: string
  note: string
}
export interface EgressConfiguredBackup {
  provider: string
  label: string
  leaves_device: boolean
}
export interface EgressCloudBackup {
  configured: EgressConfiguredBackup[]
  scheduled: boolean
  note: string
}
export interface EgressSurface {
  leaves_device: boolean
  note: string
}
export interface EgressReport {
  cloud_ai: EgressCloudAI
  cloud_backup: EgressCloudBackup
  web_clip: EgressSurface
  ocr: EgressSurface & { engine: string }
  embeddings: EgressSurface
}

export function getEgressReport(): Promise<EgressReport> {
  return request<EgressReport>('/system/egress-report')
}
