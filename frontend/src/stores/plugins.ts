import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as pluginsApi from '../api/plugins'
import type { PluginResponse } from '../types'

export const usePluginsStore = defineStore('plugins', () => {
  const plugins = ref<PluginResponse[]>([])
  const loading = ref(false)

  async function fetchAll() {
    loading.value = true
    try { plugins.value = await pluginsApi.listPlugins() }
    finally { loading.value = false }
  }

  async function install(data: { name: string; version: string; description?: string; entry_point: string }) {
    await pluginsApi.installPlugin(data)
    await fetchAll()
  }

  async function uninstall(id: number) {
    await pluginsApi.uninstallPlugin(id)
    await fetchAll()
  }

  async function enable(id: number) {
    await pluginsApi.enablePlugin(id)
    await fetchAll()
  }

  async function disable(id: number) {
    await pluginsApi.disablePlugin(id)
    await fetchAll()
  }

  return { plugins, loading, fetchAll, install, uninstall, enable, disable }
})
