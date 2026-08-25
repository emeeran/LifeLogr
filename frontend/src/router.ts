import { createRouter, createWebHistory } from 'vue-router'

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
      path: '/settings',
      name: 'settings',
      component: () => import('./components/settings/SettingsView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/calendar' },
  ],
})

export default router
