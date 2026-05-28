import { request } from './client'

export interface AISettings {
  ollama_model: string
  ollama_base_url: string
  ollama_embed_model: string
  enable_embeddings: boolean
  enable_tag_suggestions: boolean
  enable_sentiment: boolean
  enable_summarization: boolean
  enable_reflection_prompts: boolean
  enable_writer_block_helper: boolean
}

export interface StorageInfo {
  db_size_bytes: number
  media_count: number
  media_size_bytes: number
  entry_count: number
}

export interface AppSettings {
  ai: AISettings
  storage: StorageInfo
  version: string
  app_name: string
}

export interface AIModelInfo {
  name: string
  size: number
}

export const getSettings = () =>
  request<AppSettings>('/settings')

export const updateSettings = (data: { ai?: Partial<AISettings> }) =>
  request<{ status: string }>('/settings', { method: 'PUT', body: JSON.stringify(data) })

export const getOllamaModels = () =>
  request<AIModelInfo[]>('/settings/models')

export const vacuumDatabase = () =>
  request<{ status: string; reclaimed_bytes: number }>('/settings/vacuum', { method: 'POST' })

export const checkIntegrity = () =>
  request<{ status: string; message: string }>('/settings/integrity-check', { method: 'POST' })
