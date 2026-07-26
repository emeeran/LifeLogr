import { request } from './client'
import type { AiToolDef } from '../composables/aiToolRegistry'
import type {
  AIStatusResponse,
  ExpandResponse,
  GrammarSuggestion,
  RewriteResponse,
  TagSuggestionResponse,
  ThemesResponse,
} from '../types'

export const rewrite = (text: string, style: string = 'formal', instructions?: string) =>
  request<RewriteResponse>('/ai/rewrite', { method: 'POST', body: JSON.stringify({ text, style, instructions }) })

export const aiStatus = () =>
  request<AIStatusResponse>('/ai/status')

export const suggestTags = (text: string) =>
  request<TagSuggestionResponse>('/ai/suggest-tags', { method: 'POST', body: JSON.stringify({ text }) })

export const getThemes = (months: number = 6) =>
  request<ThemesResponse>(`/ai/themes?months=${months}`)

export const pullModel = (model: string) =>
  request<{ status: string; model: string }>(`/ai/pull-model?model=${encodeURIComponent(model)}`, { method: 'POST' })

// ── Smart Tools ──

export const expand = (text: string) =>
  request<ExpandResponse>('/ai/expand', { method: 'POST', body: JSON.stringify({ text }) })

// ── Generic tool runner (drives every entry in the AI tool registry) ──

export interface AiToolResult {
  text: string
  suggestions: GrammarSuggestion[]
}

/**
 * Run any AI tool by its registry definition. Builds the request body from the
 * def's `param.bodyKey`, POSTs to the def's endpoint, and reads the result text
 * from `def.resultField`. Grammar additionally returns its suggestions list.
 */
export const callAiTool = async (
  def: AiToolDef,
  text: string,
  paramValue?: string,
): Promise<AiToolResult> => {
  const body: Record<string, string> = { text }
  if (def.param) {
    body[def.param.bodyKey] = paramValue ?? def.param.default
  }
  const res = await request<Record<string, unknown>>(def.endpoint, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return {
    text: String(res[def.resultField] ?? ''),
    suggestions:
      def.kind === 'grammar'
        ? (res.suggestions as GrammarSuggestion[] | undefined) ?? []
        : [],
  }
}

// ── AI providers (OpenAI-compatible cloud + local Ollama) ──
export interface AIProvider {
  id: number
  name: string
  preset: string
  base_url: string
  model: string
  has_key: boolean
  is_active: boolean
  created_at: string
}
export interface AIProviderCreate {
  name: string
  preset: string
  base_url: string
  model: string
  api_key?: string
  is_active?: boolean
}
export interface AIProviderUpdate {
  name?: string
  base_url?: string
  model?: string
  api_key?: string
  is_active?: boolean
}
export interface ProviderPreset {
  key: string
  label: string
  base_url: string
  model: string
}

export const getProviderPresets = () => request<ProviderPreset[]>('/ai/providers/presets')
export const listProviders = () => request<AIProvider[]>('/ai/providers')
export const createProvider = (data: AIProviderCreate) =>
  request<AIProvider>('/ai/providers', { method: 'POST', body: JSON.stringify(data) })
export const updateProvider = (id: number, data: AIProviderUpdate) =>
  request<AIProvider>(`/ai/providers/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const deleteProvider = (id: number) =>
  request<void>(`/ai/providers/${id}`, { method: 'DELETE' })
export const activateProvider = (id: number) =>
  request<AIProvider>(`/ai/providers/${id}/activate`, { method: 'POST' })
export const testProvider = (id: number) =>
  request<{ status: string; model: string }>(`/ai/providers/${id}/test`, { method: 'POST' })

export interface ProviderModel {
  id: string
  owned_by?: string
}
/** Fetch the provider's real model list (drives the per-card model selector). */
export const listProviderModels = (id: number) =>
  request<{ models: ProviderModel[] }>(`/ai/providers/${id}/models`).then((r) => r.models)

/** Fetch models from an arbitrary endpoint before a provider is saved (Add form). */
export const previewProviderModels = (base_url: string, api_key?: string) =>
  request<{ models: ProviderModel[] }>(`/ai/providers/models`, {
    method: 'POST',
    body: JSON.stringify({ base_url, api_key: api_key || undefined }),
  }).then((r) => r.models)
