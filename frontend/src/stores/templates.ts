import { defineStore } from 'pinia'
import { ref } from 'vue'
import { templatesApi } from '../api/templates'
import type { TemplateResponse, TemplateCreate, TemplateUpdate } from '../types'
import { errorMessage } from '../utils/errorMessage'
import { useToastStore } from './toast'

export const useTemplatesStore = defineStore('templates', () => {
  const templates = ref<TemplateResponse[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** Set `error` + toast — the one place template failures reach the user. */
  function fail(fallback: string, e: unknown) {
    const message = errorMessage(e) || fallback
    error.value = message
    useToastStore().error(`${fallback}: ${message}`)
  }

  async function fetchAll() {
    loading.value = true
    try {
      templates.value = await templatesApi.list()
      error.value = null
    } catch (e: unknown) {
      fail('Failed to load templates', e)
    } finally {
      loading.value = false
    }
  }

  async function create(data: TemplateCreate) {
    try {
      const t = await templatesApi.create(data)
      templates.value.push(t)
      templates.value.sort((a, b) => a.name.localeCompare(b.name))
      return t
    } catch (e: unknown) {
      fail('Failed to create template', e)
      throw e
    }
  }

  async function update(id: number, data: TemplateUpdate) {
    try {
      const t = await templatesApi.update(id, data)
      const idx = templates.value.findIndex((x) => x.id === id)
      if (idx >= 0) templates.value[idx] = t
      return t
    } catch (e: unknown) {
      fail('Failed to update template', e)
      throw e
    }
  }

  async function remove(id: number) {
    try {
      await templatesApi.remove(id)
    } catch (e: unknown) {
      fail('Failed to delete template', e)
      throw e
    }
    templates.value = templates.value.filter((x) => x.id !== id)
  }

  return { templates, loading, error, fetchAll, create, update, remove }
})
