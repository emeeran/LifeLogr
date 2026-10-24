import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useAutoSave } from './useAutoSave'

/**
 * Autosave engine for the journal EntryEditor.
 *
 * Two things matter here and both are timing-shaped, so the suite runs on fake
 * timers: the debounce (a re-trigger must re-arm, not stack a second save) and
 * the in-flight guard (a debounced save that fires while a manual/slow save is
 * still in flight must bail out instead of racing it with a stale snapshot —
 * that race used to be last-write-wins data loss).
 */

type Opts = Parameters<typeof useAutoSave>[0]

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function makeOpts(overrides: Partial<Opts> = {}): Opts {
  return {
    isNew: ref(false),
    hasEntry: ref(true),
    body: ref('draft body'),
    title: ref('My title'),
    entryDate: ref('2026-10-24'),
    tagIds: ref<number[]>([3]),
    templateId: () => null,
    editingEntryId: ref(42),
    snapshot: vi.fn(),
    createEntry: vi.fn(async () => ({ id: 7 })),
    updateEntry: vi.fn(async () => undefined),
    setEditingEntryId: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
})

describe('useAutoSave', () => {
  it('defaults to a 2s debounce and follows the Settings interval', () => {
    expect(useAutoSave(makeOpts()).autosaveMs.value).toBe(2000)

    localStorage.setItem('lifelogr-autosave-interval', '5')
    expect(useAutoSave(makeOpts()).autosaveMs.value).toBe(5000)

    // Garbage / non-positive values fall back to the 2s default.
    localStorage.setItem('lifelogr-autosave-interval', 'nope')
    expect(useAutoSave(makeOpts()).autosaveMs.value).toBe(2000)
    localStorage.setItem('lifelogr-autosave-interval', '0')
    expect(useAutoSave(makeOpts()).autosaveMs.value).toBe(2000)
  })

  it('skips an empty body while creating (no blank entries)', async () => {
    const opts = makeOpts({ isNew: ref(true), body: ref('   ') })
    const auto = useAutoSave(opts)

    auto.triggerAutosave()
    expect(auto.saveState.value).toBe('idle')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(opts.createEntry).not.toHaveBeenCalled()
  })

  it('creates a new entry after the debounce and reports saved → idle', async () => {
    const opts = makeOpts({
      isNew: ref(true),
      editingEntryId: ref(null),
      templateId: () => 5,
    })
    const auto = useAutoSave(opts)

    auto.triggerAutosave()
    expect(auto.saveState.value).toBe('pending')
    expect(opts.createEntry).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(2000)
    expect(opts.createEntry).toHaveBeenCalledTimes(1)
    expect(opts.createEntry).toHaveBeenCalledWith({
      entry_date: '2026-10-24',
      title: 'My title',
      body: 'draft body',
      tag_ids: [3],
      template_id: 5,
    })
    expect(opts.setEditingEntryId).toHaveBeenCalledWith(7)
    expect(opts.snapshot).toHaveBeenCalledTimes(1)
    expect(auto.saveError.value).toBeNull()
    expect(auto.saveState.value).toBe('saved')

    // The "saved" badge reverts to idle after 3s.
    await vi.advanceTimersByTimeAsync(3000)
    expect(auto.saveState.value).toBe('idle')
  })

  it('updates the existing entry with the current title/body/tags', async () => {
    const opts = makeOpts()
    const auto = useAutoSave(opts)
    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(2000)

    expect(opts.updateEntry).toHaveBeenCalledTimes(1)
    expect(opts.updateEntry).toHaveBeenCalledWith(42, {
      title: 'My title',
      body: 'draft body',
      tag_ids: [3],
    })
    // The create path (and only it) claims a new id / snapshots.
    expect(opts.createEntry).not.toHaveBeenCalled()
    expect(opts.setEditingEntryId).not.toHaveBeenCalled()
    expect(auto.saveState.value).toBe('saved')
  })

  it('debounces: re-triggering re-arms the timer instead of saving twice', async () => {
    const opts = makeOpts()
    const auto = useAutoSave(opts)

    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(1500)
    auto.triggerAutosave() // inside the window → cancels the first arm
    await vi.advanceTimersByTimeAsync(1500) // t=3000, but the second arm is only 1500 in
    expect(opts.updateEntry).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(500) // second arm now past 2000ms
    expect(opts.updateEntry).toHaveBeenCalledTimes(1)
  })

  it('cancelSave drops the pending save without touching the API', async () => {
    const opts = makeOpts()
    const auto = useAutoSave(opts)
    auto.triggerAutosave()
    expect(auto.saveState.value).toBe('pending')
    auto.cancelSave()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(opts.updateEntry).not.toHaveBeenCalled()
  })

  it('bails out when the debounce fires while a save is already in flight', async () => {
    const gate = deferred<void>()
    const opts = makeOpts({ updateEntry: vi.fn(() => gate.promise) })
    const auto = useAutoSave(opts)

    // 1. Debounced save starts and hangs (slow network).
    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(2000)
    expect(opts.updateEntry).toHaveBeenCalledTimes(1)
    expect(auto.saveState.value).toBe('saving')

    // 2. The user keeps typing and the debounce fires again mid-flight.
    opts.body.value = 'draft body v2'
    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(2000)
    // The in-flight guard must swallow this tick: no second, racing request.
    expect(opts.updateEntry).toHaveBeenCalledTimes(1)

    // 3. The slow save lands.
    gate.resolve()
    await vi.advanceTimersByTimeAsync(0)
    expect(auto.saveState.value).toBe('saved')
    expect(auto.saveError.value).toBeNull()

    // 4. The guard is a latch, not a wedge — the next edit saves normally.
    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(2000)
    expect(opts.updateEntry).toHaveBeenCalledTimes(2)
    expect(opts.updateEntry).toHaveBeenLastCalledWith(42, {
      title: 'My title',
      body: 'draft body v2',
      tag_ids: [3],
    })
  })

  it('persists an emptied body once something was saved, but not for a pristine editor', async () => {
    const opts = makeOpts()
    const auto = useAutoSave(opts)

    // Nothing saved yet and the body is whitespace → nothing to write.
    opts.body.value = ''
    auto.triggerAutosave()
    expect(auto.saveState.value).toBe('idle')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(opts.updateEntry).not.toHaveBeenCalled()

    // Save real content first…
    opts.body.value = 'real content'
    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(2000)
    expect(opts.updateEntry).toHaveBeenCalledTimes(1)

    // …then empty it: that deletion is a legitimate edit and must persist.
    opts.body.value = ''
    auto.triggerAutosave()
    expect(auto.saveState.value).toBe('pending')
    await vi.advanceTimersByTimeAsync(2000)
    expect(opts.updateEntry).toHaveBeenCalledTimes(2)
    expect(opts.updateEntry).toHaveBeenLastCalledWith(
      42,
      expect.objectContaining({ body: '' }),
    )
  })

  it('surfaces a failed save as an error state, then recovers on the next save', async () => {
    let fail = true
    const opts = makeOpts({
      updateEntry: vi.fn(() =>
        fail ? Promise.reject(new Error('network down')) : Promise.resolve(),
      ),
    })
    const auto = useAutoSave(opts)

    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(2000)
    expect(auto.saveState.value).toBe('error')
    expect(auto.saveError.value).toBe('network down')
    expect(auto.saveState.value).not.toBe('idle') // the failure must be visible

    // The latch is released: the next edit saves normally.
    fail = false
    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(2000)
    expect(opts.updateEntry).toHaveBeenCalledTimes(2)
    expect(auto.saveState.value).toBe('saved')
    expect(auto.saveError.value).toBeNull()
  })

  it('reports an unknown failure when the error has no usable message', async () => {
    const opts = makeOpts({
      updateEntry: vi.fn(async () => {
        throw { status: 500 }
      }),
    })
    const auto = useAutoSave(opts)
    auto.triggerAutosave()
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(0)
    expect(auto.saveState.value).toBe('error')
    expect(typeof auto.saveError.value).toBe('string')
    expect(auto.saveError.value).not.toBe('')
  })
})
