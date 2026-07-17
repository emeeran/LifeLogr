import { request } from './client'
import type { OverviewResponse, WritingHabitResponse, WordCountResponse, TagStatsResponse, HeatmapResponse, MediaStatsResponse } from '../types'

export const getOverview = () => request<OverviewResponse>('/analytics/overview')
export const getHabits = () => request<WritingHabitResponse[]>('/analytics/habits')
export const getWords = () => request<WordCountResponse>('/analytics/words')
export const getTagStats = () => request<TagStatsResponse[]>('/analytics/tags')
export const getHeatmap = (year?: number) => request<HeatmapResponse>(`/analytics/heatmap${year ? `?year=${year}` : ''}`)
export const getMediaStats = () => request<MediaStatsResponse>('/analytics/media')
