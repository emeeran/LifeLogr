import { request } from './client'
import type { AiToolDef } from '../composables/aiToolRegistry'
import type {
  GrammarCheckResponse, SpellCheckResponse, RewriteResponse, AIStatusResponse,
  TagSuggestionResponse,
  ContinueWritingResponse, OnThisDayResponse, ThemesResponse,
  ExpandResponse, ChangeToneResponse,
  AnalyzeTextResponse, DefineTextResponse,
  VoiceChangeResponse, RewriteForClarityResponse,
  GrammarSuggestion,
} from '../types'

export const grammarCheck = (text: string) =>
  request<GrammarCheckResponse>('/ai/grammar-check', { method: 'POST', body: JSON.stringify({ text }) })

export const spellCheck = (text: string) =>
  request<SpellCheckResponse>('/ai/spell-check', { method: 'POST', body: JSON.stringify({ text }) })

export const rewrite = (text: string, style: string = 'formal', instructions?: string) =>
  request<RewriteResponse>('/ai/rewrite', { method: 'POST', body: JSON.stringify({ text, style, instructions }) })

export const aiStatus = () =>
  request<AIStatusResponse>('/ai/status')

export const suggestTags = (text: string) =>
  request<TagSuggestionResponse>('/ai/suggest-tags', { method: 'POST', body: JSON.stringify({ text }) })

export const continueWriting = (text: string) =>
  request<ContinueWritingResponse>('/ai/continue-writing', { method: 'POST', body: JSON.stringify({ text }) })

export const getOnThisDay = () =>
  request<OnThisDayResponse>('/ai/on-this-day')

export const getThemes = (months: number = 6) =>
  request<ThemesResponse>(`/ai/themes?months=${months}`)

export const pullModel = (model: string) =>
  request<{ status: string; model: string }>(`/ai/pull-model?model=${encodeURIComponent(model)}`, { method: 'POST' })

// ── Smart Tools ──

export const expand = (text: string) =>
  request<ExpandResponse>('/ai/expand', { method: 'POST', body: JSON.stringify({ text }) })

export const changeTone = (text: string, tone: string) =>
  request<ChangeToneResponse>('/ai/change-tone', { method: 'POST', body: JSON.stringify({ text, tone }) })

export const analyzeText = (text: string) =>
  request<AnalyzeTextResponse>('/ai/analyze-text', { method: 'POST', body: JSON.stringify({ text }) })

export const defineText = (text: string) =>
  request<DefineTextResponse>('/ai/define-text', { method: 'POST', body: JSON.stringify({ text }) })

export const changeVoice = (text: string, voice: string) =>
  request<VoiceChangeResponse>('/ai/change-voice', { method: 'POST', body: JSON.stringify({ text, voice }) })

export const rewriteForClarity = (text: string) =>
  request<RewriteForClarityResponse>('/ai/rewrite-for-clarity', { method: 'POST', body: JSON.stringify({ text }) })

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
