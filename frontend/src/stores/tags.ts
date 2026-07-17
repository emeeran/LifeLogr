import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { TagResponse, TagCreate, TagUpdate } from '../types'
import { tagsApi } from '../api/tags'

export const useTagsStore = defineStore('tags', () => {
  const tags = ref<TagResponse[]>([])
  const loading = ref(false)

  async function fetchTree() {
    loading.value = true
    try {
      tags.value = await tagsApi.tree()
    } finally {
      loading.value = false
    }
  }

  async function createTag(data: TagCreate) {
    const tag = await tagsApi.create(data)
    await fetchTree()
    return tag
  }

  async function updateTag(id: number, data: TagUpdate) {
    const tag = await tagsApi.update(id, data)
    await fetchTree()
    return tag
  }

  async function deleteTag(id: number) {
    await tagsApi.delete(id)
    await fetchTree()
  }

  return { tags, loading, fetchAll: fetchTree, fetchTree, createTag, updateTag, deleteTag }
})
