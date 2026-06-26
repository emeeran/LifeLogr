import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import type { EntryResponse, CalendarEntryResponse } from '../types'
import { entriesApi } from '../api/entries'

export const useEntriesStore = defineStore('entries', () => {
  const calendarEntries = shallowRef<CalendarEntryResponse[]>([])
  const currentEntry = ref<EntryResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastUpdated = ref(Date.now())

  function clearError() { error.value = null }

  async function fetchCalendarMonth(year: number, month: number) {
    loading.value = true
    error.value = null
    try {
      calendarEntries.value = await entriesApi.calendarMonth(year, month)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load entries'
    } finally {
      loading.value = false
    }
  }

  async function fetchEntry(id: number) {
    loading.value = true
    error.value = null
    try {
      currentEntry.value = await entriesApi.get(id)
      return currentEntry.value
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to load entry'
      return null
    } finally {
      loading.value = false
    }
  }

  async function createEntry(data: { entry_date: string; title?: string | null; body: string; tag_ids?: number[] }) {
    error.value = null
    try {
      return await entriesApi.create(data)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to create entry'
      throw e
    }
  }

  async function updateEntry(id: number, data: { title?: string | null; body?: string | null; tag_ids?: number[] | null }) {
    error.value = null
    try {
      const entry = await entriesApi.update(id, data)
      if (currentEntry.value?.id === id) currentEntry.value = entry
      return entry
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to update entry'
      throw e
    }
  }

  async function deleteEntry(id: number) {
    error.value = null
    try {
      await entriesApi.delete(id)
      if (currentEntry.value?.id === id) currentEntry.value = null
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : 'Failed to delete entry'
      throw e
    }
  }

  function refreshAll() {
    lastUpdated.value = Date.now()
  }

  return { calendarEntries, currentEntry, loading, error, lastUpdated, clearError, fetchCalendarMonth, fetchEntry, createEntry, updateEntry, deleteEntry, refreshAll }
})
