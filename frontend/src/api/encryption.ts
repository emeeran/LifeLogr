import { request } from './client'
import type { EncryptionStatusResponse } from '../types'

export const encryptEntry = (entryId: number, passphrase: string) =>
  request<EncryptionStatusResponse>(`/entries/${entryId}/encryption/encrypt`, { method: 'POST', body: JSON.stringify({ passphrase }) })

export const decryptEntry = (entryId: number, passphrase: string) =>
  request<EncryptionStatusResponse>(`/entries/${entryId}/encryption/decrypt`, { method: 'POST', body: JSON.stringify({ passphrase }) })

export const encryptionStatus = (entryId: number) =>
  request<EncryptionStatusResponse>(`/entries/${entryId}/encryption/status`)

export const encryptText = (text: string, passphrase: string) =>
  request<{ encrypted: string }>('/encryption/encrypt-text', { method: 'POST', body: JSON.stringify({ text, passphrase }) })

export const decryptText = (encryptedText: string, passphrase: string) =>
  request<{ decrypted: string }>('/encryption/decrypt-text', { method: 'POST', body: JSON.stringify({ encrypted_text: encryptedText, passphrase }) })
