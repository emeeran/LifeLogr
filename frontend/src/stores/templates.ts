import { defineStore } from 'pinia'
import { ref } from 'vue'
import { templatesApi } from '../api/templates'
import type { TemplateResponse, TemplateCreate, TemplateUpdate } from '../types'

export const useTemplatesStore = defineStore('templates', () => {
  const templates = ref<TemplateResponse[]>([])

  async function fetchAll() {
    templates.value = await templatesApi.list()
  }

  async function create(data: TemplateCreate) {
    const t = await templatesApi.create(data)
    templates.value.push(t)
    templates.value.sort((a, b) => a.name.localeCompare(b.name))
    return t
  }

  async function update(id: number, data: TemplateUpdate) {
    const t = await templatesApi.update(id, data)
    const idx = templates.value.findIndex(x => x.id === id)
    if (idx >= 0) templates.value[idx] = t
    return t
  }

  async function remove(id: number) {
    await templatesApi.remove(id)
    templates.value = templates.value.filter(x => x.id !== id)
  }

  return { templates, fetchAll, create, update, remove }
})
