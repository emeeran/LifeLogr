import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as remindersApi from '../api/reminders'
import type { ReminderResponse } from '../types'

export const useRemindersStore = defineStore('reminders', () => {
  const reminders = ref<ReminderResponse[]>([])
  const loading = ref(false)

  async function fetchAll() {
    loading.value = true
    try { reminders.value = await remindersApi.listReminders() }
    finally { loading.value = false }
  }

  async function create(data: { title: string; message?: string; reminder_time: string; days_of_week?: string }) {
    await remindersApi.createReminder(data)
    await fetchAll()
  }

  async function update(id: number, data: Record<string, unknown>) {
    await remindersApi.updateReminder(id, data)
    await fetchAll()
  }

  async function remove(id: number) {
    await remindersApi.deleteReminder(id)
    await fetchAll()
  }

  async function testNotification(id: number) {
    return await remindersApi.testNotification(id)
  }

  return { reminders, loading, fetchAll, create, update, remove, testNotification }
})
