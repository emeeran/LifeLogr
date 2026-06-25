import { computed, type Ref } from 'vue'

/**
 * Composable for auto-saving journal entries with debounce.
 * Extracts the save timer and debounce logic from EntryEditor.
 */
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
  setEditingEntryId: (id: number | null) => void
}) {
  let saveTimer: ReturnType<typeof setTimeout> | null = null

  const autosaveMs = computed(() => {
    const secs = parseInt(localStorage.getItem('lifelogr-autosave-interval') || '2')
    return (isNaN(secs) ? 2 : secs) * 1000
  })

  function cancelSave() {
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
  }

  function triggerAutosave() {
    cancelSave()
    if (!options.body.value.trim()) return

    saveTimer = setTimeout(async () => {
      if (options.isNew.value) {
        try {
          const entry = await options.createEntry({
            entry_date: options.entryDate.value,
            title: options.title.value || null,
            body: options.body.value,
            tag_ids: options.tagIds.value,
          })
          options.setEditingEntryId(entry.id)
          options.snapshot()
        } catch {
          /* ignore auto-save failures */
        }
      } else {
        await options.updateEntry(options.editingEntryId.value as number, {
          title: options.title.value || null,
          body: options.body.value,
          tag_ids: options.tagIds.value,
        })
      }
    }, autosaveMs.value)
  }

  const saving = computed(() => saveTimer !== null)

  return {
    autosaveMs,
    triggerAutosave,
    cancelSave,
    saving,
  }
}
