import { request } from './client'
import type { TagResponse, TagCreate, TagUpdate } from '../types'

export const tagsApi = {
  create(data: TagCreate): Promise<TagResponse> {
    return request('/tags', { method: 'POST', body: JSON.stringify(data) })
  },

  list(): Promise<TagResponse[]> {
    return request('/tags')
  },

  tree(): Promise<TagResponse[]> {
    return request('/tags/tree')
  },

  update(id: number, data: TagUpdate): Promise<TagResponse> {
    return request(`/tags/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
  },

  delete(id: number): Promise<void> {
    return request(`/tags/${id}`, { method: 'DELETE' })
  },
}
