import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { TagResponse, TagCreate, TagUpdate } from '../types'
import { tagsApi } from '../api/tags'
import { errorMessage } from '../utils/errorMessage'
import { useToastStore } from './toast'

export const useTagsStore = defineStore('tags', () => {
  const tags = ref<TagResponse[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** Set `error` + toast — the one place tag failures reach the user. */
  function fail(fallback: string, e: unknown) {
    const message = errorMessage(e) || fallback
    error.value = message
    useToastStore().error(`${fallback}: ${message}`)
  }

  async function fetchTree() {
    loading.value = true
    try {
      tags.value = await tagsApi.tree()
      error.value = null
    } catch (e: unknown) {
      fail('Failed to load tags', e)
    } finally {
      loading.value = false
    }
  }

  async function createTag(data: TagCreate) {
    try {
      const tag = await tagsApi.create(data)
      await fetchTree()
      return tag
    } catch (e: unknown) {
      // Creating a tag that already exists is a normal, harmless outcome of the
      // inline `#tag` autocomplete — refresh and move on without an error toast.
      const duplicate =
        ('status' in (e as object) && (e as { status?: number }).status === 409) ||
        /exist/i.test(errorMessage(e))
      if (duplicate) {
        await fetchTree()
        return null
      }
      fail('Failed to create tag', e)
      throw e
    }
  }

  async function updateTag(id: number, data: TagUpdate) {
    try {
      const tag = await tagsApi.update(id, data)
      await fetchTree()
      return tag
    } catch (e: unknown) {
      fail('Failed to update tag', e)
      throw e
    }
  }

  async function deleteTag(id: number) {
    try {
      await tagsApi.delete(id)
    } catch (e: unknown) {
      fail('Failed to delete tag', e)
      throw e
    }
    await fetchTree()
  }

  return {
    tags,
    loading,
    error,
    fetchAll: fetchTree,
    fetchTree,
    createTag,
    updateTag,
    deleteTag,
  }
})
