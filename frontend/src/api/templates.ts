import { request } from './client'
import type { TemplateCreate, TemplateResponse, TemplateUpdate } from '../types'

export const templatesApi = {
  list(): Promise<TemplateResponse[]> {
    return request('/templates')
  },
  create(data: TemplateCreate): Promise<TemplateResponse> {
    return request('/templates', { method: 'POST', body: JSON.stringify(data) })
  },
  update(id: number, data: TemplateUpdate): Promise<TemplateResponse> {
    return request(`/templates/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
  },
  remove(id: number): Promise<void> {
    return request(`/templates/${id}`, { method: 'DELETE' })
  },
}
