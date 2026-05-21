import { request } from './client'
import type { EncryptionStatusResponse } from '../types'

export const encryptEntry = (entryId: number, passphrase: string) =>
  request<EncryptionStatusResponse>(`/entries/${entryId}/encryption/encrypt`, { method: 'POST', body: JSON.stringify({ passphrase }) })

export const decryptEntry = (entryId: number, passphrase: string) =>
  request<EncryptionStatusResponse>(`/entries/${entryId}/encryption/decrypt`, { method: 'POST', body: JSON.stringify({ passphrase }) })

export const encryptionStatus = (entryId: number) =>
  request<EncryptionStatusResponse>(`/entries/${entryId}/encryption/status`)
