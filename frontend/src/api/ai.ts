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
