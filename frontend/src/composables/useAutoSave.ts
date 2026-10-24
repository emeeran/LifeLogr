import { ref, computed, type Ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { errorMessage } from '../utils/errorMessage'

/**
 * Composable for auto-saving journal entries with debounce.
 *
 * Exposes a tri-state ``saveState`` so the UI can show meaningful feedback:
 *   - ``idle``  — no pending changes
 *   - ``pending`` — dirty; waiting for the debounce timer to fire
 *   - ``saving`` — the network request is in flight
 *   - ``saved``  — just saved successfully (reverts to ``idle`` after 3s)
 */

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

export function useAutoSave(options: {
  isNew: Ref<boolean>
  hasEntry: Ref<boolean>
  body: Ref<string>
  title: Ref<string>
  entryDate: Ref<string>
  tagIds: Ref<number[]>
  templateId: () => number | null
  editingEntryId: Ref<number | null | undefined>
  snapshot: () => void
  createEntry: (data: {
    entry_date: string
    title: string | null
    body: string
    tag_ids?: number[]
    template_id?: number | null
  }) => Promise<{ id: number }>
  updateEntry: (
    id: number,
    data: {
      title: string | null
      body: string
      tag_ids: number[]
    },
  ) => Promise<unknown>
  setEditingEntryId: (id: number) => void
}) {
  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let savedTimer: ReturnType<typeof setTimeout> | null = null
  // In-flight guard: prevents a debounced autosave from racing a manual save
  // (two concurrent updateEntry calls with different snapshots = last-write-wins
  // data loss) and from overlapping itself.
  let saving = false

  const saveState = ref<SaveState>('idle')
  const saveError = ref<string | null>(null)

  // Reactive read of the Settings → Editor interval. A plain
  // `localStorage.getItem` computed never re-evaluates, so interval changes made
  // in Settings never applied until the editor was remounted; the shared
  // useLocalStorage ref (same key the settings tab writes) keeps it live.
  const autosaveInterval = useLocalStorage<number>(
    'lifelogr-autosave-interval',
    2,
  )
  const autosaveMs = computed(() => {
    const secs = Number(autosaveInterval.value)
    return (Number.isFinite(secs) && secs > 0 ? secs : 2) * 1000
  })

  // Body as of the last successful save. Emptying an entry is a legitimate edit
  // (the user deleted everything), so the autosave may persist an empty body —
  // but a genuinely empty editor (nothing saved, nothing typed) must not spam
  // the API on every keystroke of whitespace.
  let lastSavedBody = ''

  function _setSaved() {
    saveState.value = 'saved'
    if (savedTimer) clearTimeout(savedTimer)
    savedTimer = setTimeout(() => {
      saveState.value = 'idle'
    }, 3000)
  }

  function cancelSave() {
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
  }

  function triggerAutosave() {
    cancelSave()
    const bodyEmpty = !options.body.value.trim()
    if (bodyEmpty) {
      // Creating: an empty body would spawn a blank entry — keep skipping.
      if (options.isNew.value) return
      // Updating: emptying a previously-non-empty body is a real edit and must
      // persist (it used to be dropped here). Skip only when nothing was saved
      // before either — both empty means there is nothing to write.
      if (!lastSavedBody.trim()) return
    }

    saveState.value = 'pending'
    saveTimer = setTimeout(async () => {
      // Skip if a save is already in flight (e.g. a manual save just started) —
      // the next change will re-arm the timer once it finishes.
      if (saving) {
        saveTimer = null
        return
      }
      saving = true
      saveState.value = 'saving'
      try {
        if (options.isNew.value) {
          const entry = await options.createEntry({
            entry_date: options.entryDate.value,
            title: options.title.value || null,
            body: options.body.value,
            tag_ids: options.tagIds.value,
            template_id: options.templateId(),
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
        lastSavedBody = options.body.value
        saveError.value = null
        _setSaved()
      } catch (e) {
        // Surface the failure instead of silently flipping to idle — the user
        // must know their last edit didn't persist.
        saveError.value = errorMessage(e) || 'Save failed'
        saveState.value = 'error'
      } finally {
        saving = false
        saveTimer = null
      }
    }, autosaveMs.value)
  }

  return {
    autosaveMs,
    triggerAutosave,
    cancelSave,
    saveState,
    saveError,
  }
}
