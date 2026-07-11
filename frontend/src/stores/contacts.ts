import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as contactsApi from '../api/contacts'
import type { ContactResponse, ContactCreate, ContactUpdate } from '../types'

export const useContactsStore = defineStore('contacts', () => {
  const contacts = ref<ContactResponse[]>([])
  const total = ref(0)
  const loading = ref(false)
  const search = ref('')

  async function fetchAll() {
    loading.value = true
    try {
      const res = await contactsApi.listContacts({
        search: search.value || undefined,
        limit: 500,
      })
      contacts.value = res.items
      total.value = res.total
    } finally {
      loading.value = false
    }
  }

  async function create(data: ContactCreate) {
    await contactsApi.createContact(data)
    await fetchAll()
  }

  async function update(id: number, data: ContactUpdate) {
    await contactsApi.updateContact(id, data)
    await fetchAll()
  }

  async function remove(id: number) {
    await contactsApi.deleteContact(id)
    await fetchAll()
  }

  return {
    contacts, total, loading, search,
    fetchAll, create, update, remove,
  }
})
