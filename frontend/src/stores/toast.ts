import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastType = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  type: ToastType
  message: string
}

const DEFAULT_MS = 4000
/** Errors stay up longer — they usually need reading (and often acting on). */
const ERROR_MS = 7000

/**
 * App-wide toast queue. One store + one <ToasterHost /> mounted in App.vue is
 * the single place failures reach the user, so stores can surface API errors
 * without each component owning its own toast state (and so a failure in a
 * store is never silent again).
 *
 * Usage: `const toast = useToastStore(); toast.error('Save failed: ' + errorMessage(e))`
 */
export const useToastStore = defineStore('toast', () => {
  const toasts = ref<ToastItem[]>([])
  let seq = 0
  const timers = new Map<number, ReturnType<typeof setTimeout>>()

  function dismiss(id: number) {
    const timer = timers.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.delete(id)
    }
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  /** Push a toast and return its id. `timeoutMs: 0` keeps it until dismissed. */
  function push(type: ToastType, message: string, timeoutMs?: number): number {
    const id = ++seq
    const ttl = timeoutMs ?? (type === 'error' ? ERROR_MS : DEFAULT_MS)
    toasts.value = [...toasts.value, { id, type, message }]
    if (ttl > 0) timers.set(id, setTimeout(() => dismiss(id), ttl))
    return id
  }

  const success = (message: string, timeoutMs?: number) =>
    push('success', message, timeoutMs)
  const error = (message: string, timeoutMs?: number) =>
    push('error', message, timeoutMs)
  const info = (message: string, timeoutMs?: number) =>
    push('info', message, timeoutMs)

  function clearAll() {
    timers.forEach((t) => clearTimeout(t))
    timers.clear()
    toasts.value = []
  }

  return { toasts, push, dismiss, success, error, info, clearAll }
})
