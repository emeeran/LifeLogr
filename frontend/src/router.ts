import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', name: 'dashboard', component: () => import('./components/dashboard/DashboardView.vue') },
    { path: '/calendar', name: 'calendar', component: () => import('./components/calendar/CalendarGrid.vue') },
    { path: '/timeline', name: 'timeline', component: () => import('./components/timeline/TimelineView.vue') },
    { path: '/notes', name: 'notes', component: () => import('./components/notes/NotesView.vue') },
    { path: '/reminders', name: 'reminders', component: () => import('./components/reminders/RemindersView.vue') },
    { path: '/planner', name: 'planner', component: () => import('./components/planner/PlannerView.vue') },
    { path: '/contacts', name: 'contacts', component: () => import('./components/contacts/ContactsView.vue') },
    { path: '/email', name: 'email', component: () => import('./components/email/EmailView.vue') },
    { path: '/media', name: 'media', component: () => import('./components/media/MediaTimelineView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./components/settings/SettingsView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

export default router
