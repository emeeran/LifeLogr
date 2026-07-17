import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as contactsApi from '../api/contacts'
import type {
  ContactResponse, ContactCreate, ContactUpdate, ContactGroupResponse,
} from '../types'

export const useContactsStore = defineStore('contacts', () => {
  const contacts = ref<ContactResponse[]>([])
  const total = ref(0)
  const loading = ref(false)
  const search = ref('')

  const groups = ref<ContactGroupResponse[]>([])
  const activeGroupId = ref<number | null>(null) // null = all contacts
  const favoritesOnly = ref(false)

  async function fetchAll() {
    loading.value = true
    try {
      const res = await contactsApi.listContacts({
        search: search.value || undefined,
        group_id: activeGroupId.value ?? undefined,
        favorites_only: favoritesOnly.value || undefined,
        limit: 500,
      })
      contacts.value = res.items
      total.value = res.total
    } finally {
      loading.value = false
    }
  }

  async function fetchGroups() {
    groups.value = await contactsApi.listGroups()
  }

  async function create(data: ContactCreate) {
    await contactsApi.createContact(data)
    await Promise.all([fetchAll(), fetchGroups()])
  }

  async function update(id: number, data: ContactUpdate) {
    await contactsApi.updateContact(id, data)
    await Promise.all([fetchAll(), fetchGroups()])
  }

  async function remove(id: number) {
    await contactsApi.deleteContact(id)
    await Promise.all([fetchAll(), fetchGroups()])
  }

  async function toggleFavorite(c: ContactResponse) {
    const next = !c.is_favorite
    await contactsApi.updateContact(c.id, { is_favorite: next })
    c.is_favorite = next
  }

  async function createGroup(name: string, color: string | null = null) {
    await contactsApi.createGroup({ name, color })
    await fetchGroups()
  }

  async function updateGroup(id: number, name?: string, color?: string | null) {
    await contactsApi.updateGroup(id, { name, color })
    await fetchGroups()
  }

  async function removeGroup(id: number) {
    await contactsApi.deleteGroup(id)
    if (activeGroupId.value === id) activeGroupId.value = null
    await Promise.all([fetchAll(), fetchGroups()])
  }

  /** Filter by a group (null = all), or toggle favorites view. */
  function selectGroup(groupId: number | null) {
    activeGroupId.value = groupId
    favoritesOnly.value = false
    fetchAll()
  }

  function toggleFavoritesView() {
    favoritesOnly.value = !favoritesOnly.value
    if (favoritesOnly.value) activeGroupId.value = null
    fetchAll()
  }

  return {
    contacts, total, loading, search,
    groups, activeGroupId, favoritesOnly,
    fetchAll, fetchGroups, create, update, remove, toggleFavorite,
    createGroup, updateGroup, removeGroup, selectGroup, toggleFavoritesView,
  }
})
