import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './styles/main.css'
import { migrateLegacyKeys } from './utils/settings'
import { useUiStore, type ViewType } from './stores/ui'
import { useToastStore } from './stores/toast'
import { errorMessage } from './utils/errorMessage'
import { reportClientError } from './utils/clientErrors'

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

// ── Renderer error reporting ────────────────────────────────────────────────
// Without this, a component crash or an unhandled rejection in the desktop
// webview leaves an empty panel and no trace anywhere. Views are additionally
// wrapped in ErrorBoundary; this is the last line (and the only one that sees
// non-component errors).
const toast = useToastStore(pinia)

function currentView(): string | undefined {
  const name = router.currentRoute.value.name
  return typeof name === 'string' ? name : undefined
}

function describe(err: unknown): string {
  try {
    return errorMessage(err)
  } catch {
    return 'Unknown error'
  }
}

app.config.errorHandler = (err, instance, info) => {
  const message = describe(err)
  console.error('[vue]', err, info)
  try {
    toast.error(`Something went wrong: ${message}`)
  } catch {
    /* the toaster itself failed — reporting below still runs */
  }
  const component =
    (instance?.$options as { name?: string } | undefined)?.name ?? info
  reportClientError({
    message,
    stack: err instanceof Error ? err.stack : undefined,
    component,
    url: window.location.href,
    view: currentView(),
  })
}

window.addEventListener('error', (event) => {
  reportClientError({
    message: event.message || 'Unknown error',
    stack: event.error instanceof Error ? event.error.stack : undefined,
    component: 'window',
    url: window.location.href,
    view: currentView(),
  })
})

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason
  reportClientError({
    message: describe(reason),
    stack: reason instanceof Error ? reason.stack : undefined,
    component: 'promise',
    url: window.location.href,
    view: currentView(),
  })
})

app.mount('#app')
