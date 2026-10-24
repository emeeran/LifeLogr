import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useToastStore } from './toast'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

describe('toast store', () => {
  it('pushes a toast and reports it in the list', () => {
    const toast = useToastStore()
    expect(toast.toasts).toHaveLength(0)
    toast.push('error', 'Save failed')
    expect(toast.toasts).toHaveLength(1)
    expect(toast.toasts[0]).toMatchObject({
      type: 'error',
      message: 'Save failed',
    })
  })

  it('auto-dismisses after the timeout (errors live longer by default)', () => {
    const toast = useToastStore()
    toast.push('success', 'Saved')
    toast.push('error', 'Nope')
    expect(toast.toasts).toHaveLength(2)

    vi.advanceTimersByTime(4000)
    expect(toast.toasts.map((t) => t.type)).toEqual(['error'])

    vi.advanceTimersByTime(3000)
    expect(toast.toasts).toHaveLength(0)
  })

  it('a timeoutMs of 0 keeps the toast until dismissed', () => {
    const toast = useToastStore()
    const id = toast.push('info', 'stays', 0)
    vi.advanceTimersByTime(60_000)
    expect(toast.toasts).toHaveLength(1)
    toast.dismiss(id)
    expect(toast.toasts).toHaveLength(0)
  })

  it('dismiss removes only the targeted toast and cancels its timer', () => {
    const toast = useToastStore()
    const a = toast.push('info', 'a', 1000)
    const b = toast.push('info', 'b', 1000)
    toast.dismiss(a)
    expect(toast.toasts.map((t) => t.id)).toEqual([b])
    // Dismissing twice must not throw (timer already cleared).
    expect(() => toast.dismiss(a)).not.toThrow()
    vi.advanceTimersByTime(1000)
    expect(toast.toasts).toHaveLength(0)
  })

  it('success / error / info helpers set the matching type', () => {
    const toast = useToastStore()
    toast.success('ok')
    toast.error('bad')
    toast.info('fyi')
    expect(toast.toasts.map((t) => t.type)).toEqual([
      'success',
      'error',
      'info',
    ])
  })

  it('clearAll empties the queue and stops every timer', () => {
    const toast = useToastStore()
    toast.success('1')
    toast.error('2')
    toast.clearAll()
    expect(toast.toasts).toHaveLength(0)
    // No stray timers firing later.
    vi.advanceTimersByTime(60_000)
    expect(toast.toasts).toHaveLength(0)
  })
})
