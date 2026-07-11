import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as emailApi from '../api/email'
import type {
  EmailAccountResponse,
  EmailFolderResponse,
  EmailMessageListResponse,
  EmailMessageResponse,
  SpamRuleResponse,
} from '../types'

export const useEmailStore = defineStore('email', () => {
  const accounts = ref<EmailAccountResponse[]>([])
  const activeAccountId = ref<number | null>(null)
  const folders = ref<EmailFolderResponse[]>([])
  const activeFolderId = ref<number | null>(null) // null = all folders

  const messages = ref<EmailMessageListResponse[]>([])
  const selectedMessage = ref<EmailMessageResponse | null>(null)

  const search = ref('')
  const unreadOnly = ref(false)
  const spamOnly = ref(false)

  // Bulk-selection state (message ids).
  const selectedIds = ref<Set<number>>(new Set())

  const spamRules = ref<SpamRuleResponse[]>([])

  const loadingAccounts = ref(false)
  const loadingFolders = ref(false)
  const loadingMessages = ref(false)
  const loadingDetail = ref(false)
  const syncing = ref(false)

  function resetSelection() {
    selectedMessage.value = null
  }
  function clearSelection() {
    selectedIds.value = new Set()
  }
  const spamCount = ref(0)

  async function fetchAccounts() {
    loadingAccounts.value = true
    try {
      accounts.value = await emailApi.listAccounts()
      if (accounts.value.length && activeAccountId.value == null) {
        await selectAccount(accounts.value[0].id)
      } else if (!accounts.value.length) {
        activeAccountId.value = null
        folders.value = []
        messages.value = []
        resetSelection()
      }
    } finally {
      loadingAccounts.value = false
    }
  }

  async function selectAccount(accountId: number) {
    activeAccountId.value = accountId
    activeFolderId.value = null
    spamOnly.value = false
    clearSelection()
    resetSelection()
    await fetchFolders()
    await fetchMessages()
  }

  async function fetchFolders() {
    if (activeAccountId.value == null) {
      folders.value = []
      return
    }
    loadingFolders.value = true
    try {
      folders.value = await emailApi.listFolders(activeAccountId.value)
    } finally {
      loadingFolders.value = false
    }
  }

  async function refreshFolders() {
    if (activeAccountId.value == null) return
    folders.value = await emailApi.refreshFolders(activeAccountId.value)
  }

  function selectFolder(folderId: number | null) {
    activeFolderId.value = folderId
    spamOnly.value = false
    clearSelection()
    resetSelection()
    fetchMessages()
  }

  function selectSpam() {
    activeFolderId.value = null
    unreadOnly.value = false
    spamOnly.value = true
    clearSelection()
    resetSelection()
    fetchMessages()
  }

  function toggleUnread() {
    unreadOnly.value = !unreadOnly.value
    spamOnly.value = false
    clearSelection()
    fetchMessages()
  }

  async function fetchMessages() {
    if (activeAccountId.value == null) {
      messages.value = []
      return
    }
    loadingMessages.value = true
    try {
      const res = await emailApi.listMessages({
        account_id: activeAccountId.value,
        folder_id: activeFolderId.value ?? undefined,
        unread_only: unreadOnly.value || undefined,
        search: search.value || undefined,
        exclude_spam: !spamOnly.value,
        spam_only: spamOnly.value || undefined,
        limit: 200,
      })
      messages.value = res.items
    } finally {
      loadingMessages.value = false
    }
  }

  async function refreshSpamCount() {
    if (activeAccountId.value == null) { spamCount.value = 0; return }
    try {
      const res = await emailApi.listMessages({
        account_id: activeAccountId.value, spam_only: true, limit: 1,
      })
      spamCount.value = res.total
    } catch { /* ignore */ }
  }

  async function openMessage(id: number) {
    loadingDetail.value = true
    try {
      selectedMessage.value = await emailApi.getMessage(id)
      const listing = messages.value.find((m) => m.id === id)
      if (listing && !listing.is_read) {
        await emailApi.updateMessageFlags(id, { is_read: true })
        listing.is_read = true
        if (selectedMessage.value) selectedMessage.value.is_read = true
        const folder = folders.value.find((f) => f.id === listing.folder_id)
        if (folder) folder.unread_count = Math.max(0, folder.unread_count - 1)
      }
    } finally {
      loadingDetail.value = false
    }
  }

  async function toggleStar(msg: EmailMessageListResponse) {
    const next = !msg.is_starred
    await emailApi.updateMessageFlags(msg.id, { is_starred: next })
    msg.is_starred = next
    if (selectedMessage.value?.id === msg.id) selectedMessage.value.is_starred = next
  }

  async function toggleRead(msg: EmailMessageListResponse) {
    const next = !msg.is_read
    await emailApi.updateMessageFlags(msg.id, { is_read: next })
    msg.is_read = next
    if (selectedMessage.value?.id === msg.id) selectedMessage.value.is_read = next
    const folder = folders.value.find((f) => f.id === msg.folder_id)
    if (folder) folder.unread_count = Math.max(0, folder.unread_count + (next ? -1 : 1))
  }

  async function removeMessage(id: number) {
    await emailApi.deleteMessage(id)
    messages.value = messages.value.filter((m) => m.id !== id)
    if (selectedMessage.value?.id === id) resetSelection()
  }

  async function bulkDelete(ids: number[]) {
    if (!ids.length) return
    await emailApi.bulkDeleteMessages(ids)
    const idset = new Set(ids)
    messages.value = messages.value.filter((m) => !idset.has(m.id))
    if (selectedMessage.value && idset.has(selectedMessage.value.id)) resetSelection()
    clearSelection()
    await fetchFolders()
  }

  async function markSpam(msg: EmailMessageListResponse, isSpam: boolean) {
    await emailApi.markMessageSpam(msg.id, isSpam)
    msg.is_spam = isSpam
    if (selectedMessage.value?.id === msg.id) selectedMessage.value.is_spam = isSpam
    // Spam is hidden outside the Spam view; drop it from the current list then.
    if (isSpam && !spamOnly.value) {
      messages.value = messages.value.filter((m) => m.id !== msg.id)
      if (selectedMessage.value?.id === msg.id) resetSelection()
    } else if (!isSpam && spamOnly.value) {
      messages.value = messages.value.filter((m) => m.id !== msg.id)
      if (selectedMessage.value?.id === msg.id) resetSelection()
    }
    await refreshSpamCount()
  }

  function toggleSelected(id: number) {
    const next = new Set(selectedIds.value)
    next.has(id) ? next.delete(id) : next.add(id)
    selectedIds.value = next
  }
  function selectAllVisible() {
    selectedIds.value = new Set(messages.value.map((m) => m.id))
  }

  // ── Spam rules (blocklist) ──
  async function fetchSpamRules() {
    spamRules.value = await emailApi.listSpamRules()
  }
  async function addSpamRule(pattern: string, isDomain: boolean) {
    await emailApi.addSpamRule({ pattern, is_domain: isDomain })
    await fetchSpamRules()
  }
  async function removeSpamRule(id: number) {
    await emailApi.removeSpamRule(id)
    await fetchSpamRules()
  }
  async function rescore() {
    await emailApi.rescoreSpam(activeAccountId.value ?? undefined)
    await Promise.all([fetchMessages(), refreshSpamCount()])
  }

  async function syncActive() {
    if (activeAccountId.value == null) return
    syncing.value = true
    try {
      await emailApi.syncAccount(activeAccountId.value)
      await fetchFolders()
      await fetchMessages()
    } finally {
      syncing.value = false
    }
  }

  async function init() {
    await fetchAccounts()
    refreshSpamCount()
  }

  return {
    accounts, activeAccountId, folders, activeFolderId,
    messages, selectedMessage, search, unreadOnly, spamOnly,
    selectedIds, spamRules, spamCount,
    loadingAccounts, loadingFolders, loadingMessages, loadingDetail, syncing,
    init, fetchAccounts, selectAccount, fetchFolders, refreshFolders,
    selectFolder, selectSpam, toggleUnread, fetchMessages, refreshSpamCount,
    openMessage, toggleStar, toggleRead, removeMessage, bulkDelete, markSpam,
    toggleSelected, selectAllVisible, clearSelection, resetSelection,
    fetchSpamRules, addSpamRule, removeSpamRule, rescore, syncActive,
  }
})
