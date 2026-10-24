import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './styles/main.css'
import { migrateLegacyKeys } from './utils/settings'
import { useUiStore, type ViewType } from './stores/ui'

// Rename legacy `diarium-*` localStorage keys to `lifelogr-*` before any
// store/useLocalStorage binds to them. Idempotent.
migrateLegacyKeys()

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// Mirror the URL into `ui.activeView` on every confirmed navigation so the
// flag and the route can't drift: browser Back/Forward, direct URL loads and
// the `/` redirect all land on the right sidebar highlight. (The forward
// direction — sidebar clicks and programmatic jumps — pushes the route from
// `ui.setView`.) Route names not in ViewType don't exist today; ignore them.
const VIEW_NAMES: readonly string[] = ['calendar', 'timeline', 'notes', 'reminders', 'media', 'settings']
router.afterEach((to) => {
  const name = to.name
  if (typeof name !== 'string' || !VIEW_NAMES.includes(name)) return
  const ui = useUiStore(pinia)
  if (ui.activeView !== (name as ViewType)) ui.activeView = name as ViewType
})

app.mount('#app')
