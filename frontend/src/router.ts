import { createRouter, createWebHistory } from 'vue-router'
import { useUiStore } from './stores/ui'
import { useConfirm } from './composables/useConfirm'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/calendar' },
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('./components/calendar/CalendarGrid.vue'),
    },
    {
      path: '/timeline',
      name: 'timeline',
      component: () => import('./components/timeline/TimelineView.vue'),
    },
    {
      path: '/notes',
      name: 'notes',
      component: () => import('./components/notes/NotesView.vue'),
    },
    {
      path: '/reminders',
      name: 'reminders',
      component: () => import('./components/reminders/RemindersView.vue'),
    },
    {
      path: '/media',
      name: 'media',
      component: () => import('./components/media/MediaTimelineView.vue'),
    },
    {
      path: '/stats',
      name: 'stats',
      component: () => import('./components/stats/StatsView.vue'),
    },
    {
      path: '/trash',
      name: 'trash',
      component: () => import('./components/trash/TrashView.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('./components/settings/SettingsView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/calendar' },
  ],
})

/**
 * Unsaved-edit guard.
 *
 * The editors hold their buffers locally (notes autosave is OFF by design, and
 * the journal editor only autosaves after its debounce fires), and both are
 * unmounted by a route change — so navigating away with unsaved edits used to
 * drop them silently. The editors mirror their dirty state into the ui store
 * (`editorIsDirty` / `notesEditorIsDirty`); this guard is the last line of
 * defence for the route-change path.
 *
 * Deliberately separate from AppShell's save-prompt overlay, which handles
 * entry→entry switches *within* the Journal view and never changes route, so
 * the two can't double-prompt for the same edit.
 */
router.beforeEach(async () => {
  const ui = useUiStore()
  if (!ui.hasDirtyEditor) return true
  // Modal confirm via useConfirm (spec §9 ED9 — no native window.confirm);
  // the guard awaits the hosted ConfirmDialogHost in App.vue.
  const { confirm } = useConfirm()
  const leave = await confirm({
    title: 'Unsaved changes',
    message:
      'Leave this page and discard your changes? ' +
      'Click "Cancel" to stay and save first.',
    confirmLabel: 'Leave',
  })
  if (!leave) return false
  ui.clearDirtyEditors()
  return true
})

export default router
