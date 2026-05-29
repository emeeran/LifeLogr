import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/calendar' },
    { path: '/calendar', name: 'calendar', component: () => import('./components/calendar/CalendarGrid.vue') },
    { path: '/timeline', name: 'timeline', component: () => import('./components/timeline/TimelineView.vue') },
    { path: '/search', name: 'search', component: () => import('./components/search/SearchView.vue') },
    { path: '/analytics', name: 'analytics', component: () => import('./components/analytics/AnalyticsView.vue') },
    { path: '/reminders', name: 'reminders', component: () => import('./components/reminders/RemindersView.vue') },
    { path: '/media', name: 'media', component: () => import('./components/media/MediaTimelineView.vue') },
    { path: '/on-this-day', name: 'on-this-day', component: () => import('./components/onthisday/OnThisDayView.vue') },
    { path: '/settings', name: 'settings', component: () => import('./components/settings/SettingsView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/calendar' },
  ],
})

export default router
