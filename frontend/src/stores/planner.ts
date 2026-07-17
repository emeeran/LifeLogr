import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as plannerApi from '../api/planner'
import type {
  TaskListResponse, TaskResponse, TaskCreate,
  ScheduleEventResponse, AgendaItem,
} from '../types'

export const usePlannerStore = defineStore('planner', () => {
  const taskLists = ref<TaskListResponse[]>([])
  const tasks = ref<TaskResponse[]>([])
  const tasksLoading = ref(false)
  const selectedListId = ref<number | null>(null) // null = all lists
  const showCompleted = ref(false)

  const agenda = ref<AgendaItem[]>([])
  const agendaRange = ref<{ from: Date; to: Date } | null>(null)

  // ── Tasks ──
  async function fetchTaskLists() {
    taskLists.value = await plannerApi.listTaskLists()
  }

  async function fetchTasks() {
    tasksLoading.value = true
    try {
      tasks.value = await plannerApi.listTasks({
        list_id: selectedListId.value ?? undefined,
        include_completed: showCompleted.value,
      })
    } finally {
      tasksLoading.value = false
    }
  }

  async function createTask(data: TaskCreate) {
    await plannerApi.createTask(data)
    await fetchTasks()
  }
  async function updateTask(id: number, data: Partial<TaskCreate>) {
    await plannerApi.updateTask(id, data)
    await fetchTasks()
  }
  async function toggleComplete(task: TaskResponse) {
    await plannerApi.setTaskCompleted(task.id, !task.is_completed)
    await fetchTasks()
  }
  async function removeTask(id: number) {
    await plannerApi.deleteTask(id)
    await fetchTasks()
  }

  async function createList(name: string) {
    await plannerApi.createTaskList({ name })
    await fetchTaskLists()
  }
  async function removeList(id: number) {
    await plannerApi.deleteTaskList(id)
    if (selectedListId.value === id) selectedListId.value = null
    await Promise.all([fetchTaskLists(), fetchTasks()])
  }

  // ── Schedule ──
  async function fetchAgenda(from: Date, to: Date) {
    agendaRange.value = { from, to }
    const res = await plannerApi.getAgenda(from, to)
    agenda.value = res.items
  }
  async function createEvent(data: ScheduleEventResponse | Record<string, unknown>) {
    await plannerApi.createEvent(data as never)
    if (agendaRange.value) await fetchAgenda(agendaRange.value.from, agendaRange.value.to)
  }
  async function deleteEvent(id: number) {
    await plannerApi.deleteEvent(id)
    if (agendaRange.value) await fetchAgenda(agendaRange.value.from, agendaRange.value.to)
  }

  return {
    taskLists, tasks, tasksLoading, selectedListId, showCompleted,
    agenda, agendaRange,
    fetchTaskLists, fetchTasks, createTask, updateTask, toggleComplete, removeTask,
    createList, removeList,
    fetchAgenda, createEvent, deleteEvent,
  }
})
