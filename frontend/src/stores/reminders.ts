import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as remindersApi from '../api/reminders'
import type { ReminderResponse } from '../types'
import { errorMessage } from '../utils/errorMessage'
import { useToastStore } from './toast'

export const useRemindersStore = defineStore('reminders', () => {
  const reminders = ref<ReminderResponse[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** Set `error` + toast — the one place reminder failures reach the user. */
  function fail(fallback: string, e: unknown) {
    const message = errorMessage(e) || fallback
    error.value = message
    useToastStore().error(`${fallback}: ${message}`)
  }

  async function fetchAll() {
    loading.value = true
    try {
      reminders.value = await remindersApi.listReminders()
      error.value = null
    } catch (e: unknown) {
      fail('Failed to load reminders', e)
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
      fail('Failed to create reminder', e)
      throw e
    }
    await fetchAll()
  }

  async function update(id: number, data: Record<string, unknown>) {
    try {
      await remindersApi.updateReminder(id, data)
    } catch (e: unknown) {
      fail('Failed to update reminder', e)
      throw e
    }
    await fetchAll()
  }

  async function remove(id: number) {
    try {
      await remindersApi.deleteReminder(id)
    } catch (e: unknown) {
      fail('Failed to delete reminder', e)
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
