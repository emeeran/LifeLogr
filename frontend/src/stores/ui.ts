import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import router from '../router'

export type ViewType =
  'calendar' | 'timeline' | 'notes' | 'reminders' | 'media' | 'settings'
export type DrawerPanel = 'ai' | 'attachments'

export const useUiStore = defineStore('ui', () => {
  const activeView = useLocalStorage<ViewType>('lifelogr-view', 'calendar')
  const sidebarCollapsed = useLocalStorage('lifelogr-sidebar-collapsed', false)
  // Persisted: reopening the app keeps the layout the user left it in.
  const detailPanelOpen = useLocalStorage('lifelogr-detail-panel-open', true)
  const editingEntryId = ref<number | null>(null)
  const newEntryDate = ref<string | null>(null)
  const darkMode = useLocalStorage('lifelogr-dark', true)
  const fontFamily = useLocalStorage<string>('lifelogr-font', 'system-ui')
  const fontSize = useLocalStorage<number>('lifelogr-font-size', 14)
  const rightPanelWidth = useLocalStorage<number>(
    'lifelogr-right-panel-width',
    480,
  )
  const defaultTitle = useLocalStorage<string>('lifelogr-default-title', '')

  // Pending switch (used by save-prompt dialog)
  const pendingSwitch = ref<{ entryId: number; date?: string } | null>(null)
  const showSavePrompt = ref(false)
  // Shared editor-dirty flags, one per editor surface. The journal editor owns
  // `editorIsDirty`; the notes editor mirrors its `isDirty` into
  // `notesEditorIsDirty` so the router guard (see router.ts) can block route
  // changes that would silently drop unsaved edits from either surface.
  const editorIsDirty = ref(false)
  const notesEditorIsDirty = ref(false)
  const hasDirtyEditor = computed(
    () => editorIsDirty.value || notesEditorIsDirty.value,
  )

  /** Clear both dirty flags (the user chose to abandon the edits). */
  function clearDirtyEditors() {
    editorIsDirty.value = false
    notesEditorIsDirty.value = false
  }

  const showEditor = computed(() => editingEntryId.value !== null)

  // Global search palette
  const searchPaletteOpen = ref(false)

  // Lets a component (e.g. the health banner) jump straight to a Settings tab.
  const requestedSettingsTab = ref<string | null>(null)

  // Tool drawer (side panel — only one panel open at a time)
  const activeDrawer = ref<DrawerPanel | null>(null)

  // Scribble pad
  const scribbleOpen = useLocalStorage('lifelogr-scribble-open', false)

  // Distraction-free writing: hides sidebar + center list, full-width editor.
  // Distinct from the editor's own focusMode/fullscreen (a per-editor control).
  const zenMode = useLocalStorage('lifelogr-zen-mode', false)

  function openSearchPalette() {
    searchPaletteOpen.value = true
  }
  function closeSearchPalette() {
    searchPaletteOpen.value = false
  }

  function toggleDrawer(panel: DrawerPanel) {
    activeDrawer.value = activeDrawer.value === panel ? null : panel
  }
  function closeDrawer() {
    activeDrawer.value = null
  }

  function toggleScribble() {
    scribbleOpen.value = !scribbleOpen.value
  }

  function toggleZenMode() {
    zenMode.value = !zenMode.value
  }

  /**
   * Navigate to a view. `ViewType` doubles as the vue-router route name, so
   * the URL is the source of truth: this pushes the route (a no-op when
   * already there) and mirrors the flag on success only, so an aborted
   * navigation (the unsaved-edit guard) never leaves the sidebar pointing at
   * a view the user was kept out of. `router.afterEach` (main.ts) syncs the
   * flag back for browser Back/Forward and the initial load.
   */
  function setView(view: ViewType) {
    void router.push({ name: view }).then(
      () => {
        activeView.value = view
      },
      () => {
        // Navigation aborted/duplicated — leave current state untouched.
      },
    )
  }

  /** Switch to a specific Settings tab (used by the health banner's "View"). */
  function requestSettingsTab(id: string) {
    requestedSettingsTab.value = id
    setView('settings')
  }

  /** Check dirty and request edit switch — returns true if switched immediately */
  function requestEdit(entryId: number, date?: string) {
    if (showEditor.value && editorIsDirty.value) {
      pendingSwitch.value = { entryId, date }
      showSavePrompt.value = true
      return false
    }
    startEditing(entryId, date)
    return true
  }

  /** Like requestEdit, but for a brand-new entry on a given date (the editor
   *  pre-fills that date via newEntryDate). Same dirty-editor guard. */
  function requestNewEntry(date?: string) {
    return requestEdit(-1, date)
  }

  function confirmSwitchSave() {
    showSavePrompt.value = false
    // Caller (AppShell) handles save then calls startEditing
  }

  function confirmSwitchDiscard() {
    showSavePrompt.value = false
    if (pendingSwitch.value) {
      startEditing(pendingSwitch.value.entryId, pendingSwitch.value.date)
      pendingSwitch.value = null
    }
  }

  function cancelSwitch() {
    showSavePrompt.value = false
    pendingSwitch.value = null
  }

  function startEditing(entryId: number | null, date?: string) {
    editingEntryId.value = entryId
    newEntryDate.value = date ?? null
  }

  function toggleDetailPanel() {
    detailPanelOpen.value = !detailPanelOpen.value
  }

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function toggleTheme() {
    darkMode.value = !darkMode.value
    applyTheme()
  }

  function applyTheme() {
    const el = document.documentElement
    el.classList.toggle('dark', darkMode.value)
    el.style.setProperty('--editor-font', fontFamily.value)
    el.style.setProperty('--editor-font-size', `${fontSize.value}px`)
  }

  function setFontFamily(f: string) {
    fontFamily.value = f
    document.documentElement.style.setProperty('--editor-font', f)
  }

  function setFontSize(s: number) {
    fontSize.value = s
    document.documentElement.style.setProperty('--editor-font-size', `${s}px`)
  }

  function setRightPanelWidth(w: number) {
    const maxW = Math.min(w, window.innerWidth * 0.5)
    rightPanelWidth.value = Math.max(280, maxW)
  }

  // Apply on store creation so refresh keeps theme + font prefs
  applyTheme()

  // Auto-collapse sidebar on small screens
  if (typeof window !== 'undefined' && window.innerWidth < 768) {
    sidebarCollapsed.value = true
  }

  // Default to new entry on first load so three-column layout is visible
  if (editingEntryId.value === null) {
    editingEntryId.value = -1
  }

  return {
    activeView,
    sidebarCollapsed,
    detailPanelOpen,
    editingEntryId,
    newEntryDate,
    darkMode,
    fontFamily,
    fontSize,
    rightPanelWidth,
    defaultTitle,
    showEditor,
    showSavePrompt,
    pendingSwitch,
    editorIsDirty,
    notesEditorIsDirty,
    hasDirtyEditor,
    clearDirtyEditors,
    searchPaletteOpen,
    activeDrawer,
    scribbleOpen,
    zenMode,
    setView,
    startEditing,
    requestEdit,
    requestNewEntry,
    confirmSwitchSave,
    confirmSwitchDiscard,
    cancelSwitch,
    toggleDetailPanel,
    toggleSidebar,
    toggleTheme,
    setFontFamily,
    setFontSize,
    setRightPanelWidth,
    openSearchPalette,
    closeSearchPalette,
    toggleDrawer,
    closeDrawer,
    toggleScribble,
    toggleZenMode,
    requestedSettingsTab,
    requestSettingsTab,
  }
})
