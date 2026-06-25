import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './styles/main.css'
import { migrateLegacyKeys } from './utils/settings'

// Rename legacy `diarium-*` localStorage keys to `lifelogr-*` before any
// store/useLocalStorage binds to them. Idempotent.
migrateLegacyKeys()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
