import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useLocalStorage } from '@vueuse/core'

export type ViewType = 'calendar' | 'timeline' | 'notes' | 'search' | 'on-this-day' | 'analytics' | 'reminders' | 'media' | 'settings' | 'planner' | 'email' | 'contacts'
export type DrawerPanel = 'ai' | 'attachments'

export const useUiStore = defineStore('ui', () => {
  const activeView = useLocalStorage<ViewType>('lifelogr-view', 'calendar')
  const sidebarCollapsed = useLocalStorage('lifelogr-sidebar-collapsed', false)
  const detailPanelOpen = ref(true)
  const editingEntryId = ref<number | null>(null)
  const newEntryDate = ref<string | null>(null)
  const darkMode = useLocalStorage('lifelogr-dark', true)
  const fontFamily = useLocalStorage<string>('lifelogr-font', 'system-ui')
  const fontSize = useLocalStorage<number>('lifelogr-font-size', 14)
  const rightPanelWidth = useLocalStorage<number>('lifelogr-right-panel-width', 480)
  const defaultTitle = useLocalStorage<string>('lifelogr-default-title', '')

  // Pending switch (used by save-prompt dialog)
  const pendingSwitch = ref<{ entryId: number; date?: string } | null>(null)
  const showSavePrompt = ref(false)
  const editorIsDirty = ref(false)

  const showEditor = computed(() => editingEntryId.value !== null)

  // Global search palette
  const searchPaletteOpen = ref(false)

  // Tool drawer (side panel — only one panel open at a time)
  const activeDrawer = ref<DrawerPanel | null>(null)

  // Scribble pad
  const scribbleOpen = useLocalStorage('lifelogr-scribble-open', false)

  function openSearchPalette() { searchPaletteOpen.value = true }
  function closeSearchPalette() { searchPaletteOpen.value = false }

  function toggleDrawer(panel: DrawerPanel) {
    activeDrawer.value = activeDrawer.value === panel ? null : panel
  }
  function closeDrawer() { activeDrawer.value = null }

  function toggleScribble() { scribbleOpen.value = !scribbleOpen.value }

  function setView(view: ViewType) {
    activeView.value = view
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
    activeView, sidebarCollapsed, detailPanelOpen, editingEntryId, newEntryDate,
    darkMode, fontFamily, fontSize, rightPanelWidth, defaultTitle, showEditor,
    showSavePrompt, pendingSwitch, editorIsDirty, searchPaletteOpen, activeDrawer,
    scribbleOpen,
    setView, startEditing, requestEdit, confirmSwitchSave, confirmSwitchDiscard, cancelSwitch,
    toggleDetailPanel, toggleSidebar, toggleTheme, setFontFamily, setFontSize, setRightPanelWidth,
    openSearchPalette, closeSearchPalette, toggleDrawer, closeDrawer, toggleScribble,
  }
})
