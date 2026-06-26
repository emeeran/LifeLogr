import { ref, computed, type Ref } from 'vue'

/**
 * Composable for auto-saving journal entries with debounce.
 *
 * Exposes a tri-state ``saveState`` so the UI can show meaningful feedback:
 *   - ``idle``  — no pending changes
 *   - ``pending`` — dirty; waiting for the debounce timer to fire
 *   - ``saving`` — the network request is in flight
 *   - ``saved``  — just saved successfully (reverts to ``idle`` after 3s)
 */

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved'

export function useAutoSave(options: {
  isNew: Ref<boolean>
  hasEntry: Ref<boolean>
  body: Ref<string>
  title: Ref<string>
  entryDate: Ref<string>
  tagIds: Ref<number[]>
  editingEntryId: Ref<number | null | undefined>
  snapshot: () => void
  createEntry: (data: {
    entry_date: string
    title: string | null
    body: string
    tag_ids?: number[]
  }) => Promise<{ id: number }>
  updateEntry: (id: number, data: {
    title: string | null
    body: string
    tag_ids: number[]
  }) => Promise<unknown>
  setEditingEntryId: (id: number) => void
}) {
  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let savedTimer: ReturnType<typeof setTimeout> | null = null

  const saveState = ref<SaveState>('idle')

  const autosaveMs = computed(() => {
    const secs = parseInt(localStorage.getItem('lifelogr-autosave-interval') || '2')
    return (isNaN(secs) ? 2 : secs) * 1000
  })

  function _setSaved() {
    saveState.value = 'saved'
    if (savedTimer) clearTimeout(savedTimer)
    savedTimer = setTimeout(() => { saveState.value = 'idle' }, 3000)
  }

  function cancelSave() {
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
  }

  function triggerAutosave() {
    cancelSave()
    if (!options.body.value.trim()) return

    saveState.value = 'pending'
    saveTimer = setTimeout(async () => {
      saveState.value = 'saving'
      try {
        if (options.isNew.value) {
          const entry = await options.createEntry({
            entry_date: options.entryDate.value,
            title: options.title.value || null,
            body: options.body.value,
            tag_ids: options.tagIds.value,
          })
          options.setEditingEntryId(entry.id)
          options.snapshot()
        } else {
          await options.updateEntry(options.editingEntryId.value as number, {
            title: options.title.value || null,
            body: options.body.value,
            tag_ids: options.tagIds.value,
          })
        }
        _setSaved()
      } catch {
        saveState.value = 'idle'
        /* ignore auto-save failures */
      } finally {
        saveTimer = null
      }
    }, autosaveMs.value)
  }

  return {
    autosaveMs,
    triggerAutosave,
    cancelSave,
    saveState,
  }
}
