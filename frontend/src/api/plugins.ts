import { request } from './client'
import type { PluginResponse, PluginInstall, PluginHookResponse } from '../types'

export const installPlugin = (data: PluginInstall) =>
  request<PluginResponse>('/plugins', { method: 'POST', body: JSON.stringify(data) })

export const listPlugins = () =>
  request<PluginResponse[]>('/plugins')

export const uninstallPlugin = (id: number) =>
  request<void>(`/plugins/${id}`, { method: 'DELETE' })

export const enablePlugin = (id: number) =>
  request<PluginResponse>(`/plugins/${id}/enable`, { method: 'POST' })

export const disablePlugin = (id: number) =>
  request<PluginResponse>(`/plugins/${id}/disable`, { method: 'POST' })

export const getPluginHooks = (id: number) =>
  request<PluginHookResponse[]>(`/plugins/${id}/hooks`)

export const listAllHooks = () =>
  request<Record<string, Array<[number, string]>>>('/plugins/hooks/registry')
