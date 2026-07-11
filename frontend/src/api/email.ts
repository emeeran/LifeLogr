import { request, API_ORIGIN } from './client'
import type {
  EmailAccountCreate,
  EmailAccountResponse,
  EmailAccountTestResult,
  EmailAccountUpdate,
  EmailCompose,
  EmailFolderResponse,
  EmailListParams,
  EmailMessageListResponse,
  EmailMessageListResult,
  EmailMessageResponse,
  EmailSendResult,
  SpamRuleCreate,
  SpamRuleResponse,
  TempAttachmentResponse,
} from '../types'

const BASE = '/email'

// ── Accounts ──

export const listAccounts = () =>
  request<EmailAccountResponse[]>(`${BASE}/accounts`)

export const createAccount = (data: EmailAccountCreate) =>
  request<EmailAccountResponse>(`${BASE}/accounts`, { method: 'POST', body: JSON.stringify(data) })

export const updateAccount = (id: number, data: EmailAccountUpdate) =>
  request<EmailAccountResponse>(`${BASE}/accounts/${id}`, { method: 'PUT', body: JSON.stringify(data) })

export const deleteAccount = (id: number) =>
  request<void>(`${BASE}/accounts/${id}`, { method: 'DELETE' })

export const testAccount = (id: number) =>
  request<EmailAccountTestResult>(`${BASE}/accounts/${id}/test`, { method: 'POST' })

export const syncAccount = (id: number) =>
  request<{ new_messages: number }>(`${BASE}/accounts/${id}/sync`, { method: 'POST' })

// ── Folders ──

export const listFolders = (accountId: number) =>
  request<EmailFolderResponse[]>(`${BASE}/accounts/${accountId}/folders`)

export const refreshFolders = (accountId: number) =>
  request<EmailFolderResponse[]>(`${BASE}/accounts/${accountId}/folders/refresh`, { method: 'POST' })

export const updateFolder = (folderId: number, data: { sync_enabled?: boolean; display_name?: string }) =>
  request<EmailFolderResponse>(`${BASE}/folders/${folderId}`, { method: 'PATCH', body: JSON.stringify(data) })

// ── Messages ──

export const listMessages = (params?: EmailListParams) => {
  const qs = new URLSearchParams()
  if (params?.account_id != null) qs.set('account_id', String(params.account_id))
  if (params?.folder_id != null) qs.set('folder_id', String(params.folder_id))
  if (params?.unread_only) qs.set('unread_only', 'true')
  if (params?.starred_only) qs.set('starred_only', 'true')
  if (params?.search) qs.set('search', params.search)
  if (params?.exclude_spam != null) qs.set('exclude_spam', String(params.exclude_spam))
  if (params?.spam_only) qs.set('spam_only', 'true')
  if (params?.offset != null) qs.set('offset', String(params.offset))
  if (params?.limit != null) qs.set('limit', String(params.limit))
  const tail = qs.toString()
  return request<EmailMessageListResult>(`${BASE}/messages${tail ? `?${tail}` : ''}`)
}

export const getMessage = (id: number) =>
  request<EmailMessageResponse>(`${BASE}/messages/${id}`)

export const updateMessageFlags = (id: number, data: { is_read?: boolean; is_starred?: boolean }) =>
  request(`${BASE}/messages/${id}/flags`, { method: 'PATCH', body: JSON.stringify(data) })

export const deleteMessage = (id: number) =>
  request<void>(`${BASE}/messages/${id}`, { method: 'DELETE' })

export const bulkDeleteMessages = (ids: number[]) =>
  request<void>(`${BASE}/messages/bulk-delete`, { method: 'POST', body: JSON.stringify(ids) })

export const markMessageSpam = (id: number, isSpam: boolean) =>
  request<EmailMessageListResponse>(`${BASE}/messages/${id}/spam`, { method: 'PATCH', body: JSON.stringify({ is_spam: isSpam }) })

export const blockSender = (id: number, action: 'junk' | 'delete', scope: 'domain' | 'sender' = 'domain') =>
  request<{ rule: import('../types').SpamRuleResponse; action: 'junk' | 'delete'; affected: number }>(
    `${BASE}/messages/${id}/block`,
    { method: 'POST', body: JSON.stringify({ action, scope }) },
  )

// ── Spam filter ──

export const listSpamRules = () => request<SpamRuleResponse[]>(`${BASE}/spam/rules`)
export const addSpamRule = (data: SpamRuleCreate) =>
  request<SpamRuleResponse>(`${BASE}/spam/rules`, { method: 'POST', body: JSON.stringify(data) })
export const removeSpamRule = (id: number) =>
  request<void>(`${BASE}/spam/rules/${id}`, { method: 'DELETE' })
export const rescoreSpam = (accountId?: number) => {
  const qs = new URLSearchParams()
  if (accountId != null) qs.set('account_id', String(accountId))
  const tail = qs.toString()
  return request<{ rescored: number }>(`${BASE}/spam/rescore${tail ? `?${tail}` : ''}`, { method: 'POST' })
}

// ── Compose ──

export const sendMessage = (data: EmailCompose) =>
  request<EmailSendResult>(`${BASE}/compose/send`, { method: 'POST', body: JSON.stringify(data) })

export const saveDraft = (data: EmailCompose) =>
  request<EmailSendResult>(`${BASE}/compose/draft`, { method: 'POST', body: JSON.stringify(data) })

export const uploadTempAttachment = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return request<TempAttachmentResponse>(`${BASE}/attachments`, { method: 'POST', body: fd })
}

/** Trigger a browser download for a stored attachment. */
export async function downloadAttachment(messageId: number, attachmentId: number, filename: string): Promise<void> {
  const res = await fetch(`${API_ORIGIN}/api/v1${BASE}/messages/${messageId}/attachments/${attachmentId}`)
  if (!res.ok) throw new Error(`Download failed: ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
