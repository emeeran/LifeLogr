import { request } from './client'
import type {
  GrammarCheckResponse, SpellCheckResponse, RewriteResponse, AIStatusResponse,
  TagSuggestionResponse, EntryAnalysisResponse, SimilarEntriesResponse,
  ContinueWritingResponse, OnThisDayResponse, ThemesResponse, DigestResponse,
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

export const getEntryAnalysis = (entryId: number) =>
  request<EntryAnalysisResponse>(`/ai/entry-analysis/${entryId}`)

export const runEntryAnalysis = (entryId: number) =>
  request<EntryAnalysisResponse>(`/ai/entry-analysis/${entryId}/run`, { method: 'POST' })

export const findSimilar = (entryId: number, topK: number = 5) =>
  request<SimilarEntriesResponse>(`/ai/similar/${entryId}?top_k=${topK}`)

export const continueWriting = (text: string) =>
  request<ContinueWritingResponse>('/ai/continue-writing', { method: 'POST', body: JSON.stringify({ text }) })

export const getOnThisDay = () =>
  request<OnThisDayResponse>('/ai/on-this-day')

export const getThemes = (months: number = 6) =>
  request<ThemesResponse>(`/ai/themes?months=${months}`)

export const listDigests = (limit: number = 10) =>
  request<DigestResponse[]>(`/ai/digests?limit=${limit}`)

export const getLatestDigest = () =>
  request<DigestResponse | null>('/ai/digests/latest')

export const generateDigest = () =>
  request<DigestResponse>('/ai/digests/generate', { method: 'POST' })

export const pullModel = (model: string) =>
  request<{ status: string; model: string }>(`/ai/pull-model?model=${encodeURIComponent(model)}`, { method: 'POST' })
