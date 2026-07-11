import { request } from './client'
import type {
  TaskListResponse, TaskListCreate,
  TaskResponse, TaskCreate, TaskUpdate,
  ScheduleEventResponse, ScheduleEventCreate, ScheduleEventUpdate,
  AgendaResponse,
} from '../types'

// ── Task lists ────────────────────────────────────────────────────────────
export const listTaskLists = () => request<TaskListResponse[]>('/planner/lists')
export const createTaskList = (data: TaskListCreate) =>
  request<TaskListResponse>('/planner/lists', { method: 'POST', body: JSON.stringify(data) })
export const updateTaskList = (id: number, data: Partial<TaskListCreate>) =>
  request<TaskListResponse>(`/planner/lists/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const deleteTaskList = (id: number) =>
  request<void>(`/planner/lists/${id}`, { method: 'DELETE' })

// ── Tasks ─────────────────────────────────────────────────────────────────
export const listTasks = (params?: { list_id?: number; include_completed?: boolean; overdue_only?: boolean }) => {
  const qs = new URLSearchParams()
  if (params?.list_id != null) qs.set('list_id', String(params.list_id))
  if (params?.include_completed) qs.set('include_completed', 'true')
  if (params?.overdue_only) qs.set('overdue_only', 'true')
  const tail = qs.toString()
  return request<TaskResponse[]>(tail ? `/planner/tasks?${tail}` : '/planner/tasks')
}
export const createTask = (data: TaskCreate) =>
  request<TaskResponse>('/planner/tasks', { method: 'POST', body: JSON.stringify(data) })
export const updateTask = (id: number, data: TaskUpdate) =>
  request<TaskResponse>(`/planner/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const setTaskCompleted = (id: number, completed: boolean) =>
  request<TaskResponse>(`/planner/tasks/${id}/complete`, { method: 'PATCH', body: JSON.stringify({ completed }) })
export const deleteTask = (id: number) =>
  request<void>(`/planner/tasks/${id}`, { method: 'DELETE' })
export const reorderTasks = (items: { id: number; new_sort_order: number }[]) =>
  request<{ reordered: number }>('/planner/tasks/reorder', {
    method: 'POST',
    body: JSON.stringify({ items }),
  })

// ── Schedule events ───────────────────────────────────────────────────────
const fmt = (d: Date) => d.toISOString().replace(/\.\d{3}Z$/, '') // naive local-ish, drop ms/Z

export const listEvents = (from?: Date, to?: Date) => {
  const qs = new URLSearchParams()
  if (from) qs.set('from', fmt(from))
  if (to) qs.set('to', fmt(to))
  const tail = qs.toString()
  return request<ScheduleEventResponse[]>(tail ? `/planner/events?${tail}` : '/planner/events')
}
export const getAgenda = (from: Date, to: Date) => {
  const qs = new URLSearchParams({ from: fmt(from), to: fmt(to) })
  return request<AgendaResponse>(`/planner/agenda?${qs.toString()}`)
}
export const createEvent = (data: ScheduleEventCreate) =>
  request<ScheduleEventResponse>('/planner/events', { method: 'POST', body: JSON.stringify(data) })
export const updateEvent = (id: number, data: ScheduleEventUpdate) =>
  request<ScheduleEventResponse>(`/planner/events/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
export const deleteEvent = (id: number) =>
  request<void>(`/planner/events/${id}`, { method: 'DELETE' })
