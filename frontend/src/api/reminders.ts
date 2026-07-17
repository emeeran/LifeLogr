import { request } from './client'
import type { ReminderResponse, ReminderCreate, ReminderUpdate } from '../types'

export const createReminder = (data: ReminderCreate) =>
  request<ReminderResponse>('/reminders', { method: 'POST', body: JSON.stringify(data) })

export const listReminders = () =>
  request<ReminderResponse[]>('/reminders')

export const updateReminder = (id: number, data: ReminderUpdate) =>
  request<ReminderResponse>(`/reminders/${id}`, { method: 'PATCH', body: JSON.stringify(data) })

export const deleteReminder = (id: number) =>
  request<void>(`/reminders/${id}`, { method: 'DELETE' })

export const testNotification = (id: number) =>
  request<{ sent: boolean; title: string }>(`/reminders/${id}/test`, { method: 'POST' })
