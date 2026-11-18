import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as remindersApi from '../api/reminders'
import type { ReminderResponse } from '../types'
import { failStoreError } from './storeError'

export const useRemindersStore = defineStore('reminders', () => {
  const reminders = ref<ReminderResponse[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)


  async function fetchAll() {
    loading.value = true
    try {
      reminders.value = await remindersApi.listReminders()
      error.value = null
    } catch (e: unknown) {
      failStoreError(error, 'Failed to load reminders', e)
    } finally {
      loading.value = false
    }
  }

  async function create(data: {
    title: string
    message?: string
    reminder_time: string
    days_of_week?: string
  }) {
    try {
      await remindersApi.createReminder(data)
    } catch (e: unknown) {
      failStoreError(error, 'Failed to create reminder', e)
      throw e
    }
    await fetchAll()
  }

  async function update(id: number, data: Record<string, unknown>) {
    try {
      await remindersApi.updateReminder(id, data)
    } catch (e: unknown) {
      failStoreError(error, 'Failed to update reminder', e)
      throw e
    }
    await fetchAll()
  }

  async function remove(id: number) {
    try {
      await remindersApi.deleteReminder(id)
    } catch (e: unknown) {
      failStoreError(error, 'Failed to delete reminder', e)
      throw e
    }
    await fetchAll()
  }

  async function testNotification(id: number) {
    return await remindersApi.testNotification(id)
  }

  return {
    reminders,
    loading,
    error,
    fetchAll,
    create,
    update,
    remove,
    testNotification,
  }
})
