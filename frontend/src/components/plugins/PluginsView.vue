<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePluginsStore } from '../../stores/plugins'
import { Puzzle, Plus, Trash2, Power, PowerOff } from 'lucide-vue-next'

const store = usePluginsStore()
const showInstall = ref(false)
const form = ref({ name: '', version: '1.0.0', description: '', entry_point: '' })

onMounted(() => store.fetchAll())

async function installPlugin() {
  if (!form.value.name || !form.value.entry_point) return
  await store.install(form.value)
  showInstall.value = false
  form.value = { name: '', version: '1.0.0', description: '', entry_point: '' }
}
</script>

<template>
  <div class="h-full overflow-y-auto p-6 space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-text-primary flex items-center gap-2"><Puzzle :size="24" /> Plugins</h1>
      <button @click="showInstall = !showInstall"
        class="px-3 py-1.5 bg-accent text-white text-sm rounded hover:bg-accent/90 flex items-center gap-1">
        <Plus :size="16" /> Install
      </button>
    </div>

    <!-- Install Form -->
    <div v-if="showInstall" class="bg-surface rounded-lg p-4 border border-border space-y-3">
      <input v-model="form.name" placeholder="Plugin name"
        class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
      <input v-model="form.version" placeholder="Version"
        class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
      <input v-model="form.description" placeholder="Description (optional)"
        class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
      <input v-model="form.entry_point" placeholder="Entry point (e.g., plugins.hello_world)"
        class="w-full px-3 py-2 bg-surface-hover border border-border rounded text-sm text-text-primary" />
      <div class="flex gap-2">
        <button @click="installPlugin" class="px-4 py-1.5 bg-accent text-white text-sm rounded hover:bg-accent/90">Install</button>
        <button @click="showInstall = false" class="px-4 py-1.5 bg-surface-hover text-text-secondary text-sm rounded hover:bg-border">Cancel</button>
      </div>
    </div>

    <!-- Plugin List -->
    <div v-if="store.loading" class="text-text-secondary text-sm">Loading...</div>
    <div v-else-if="store.plugins.length === 0" class="text-text-secondary text-sm py-8 text-center">
      No plugins installed. Install a plugin to extend Diarilinux's functionality.
    </div>
    <div v-else class="space-y-3">
      <div v-for="p in store.plugins" :key="p.id"
        class="bg-surface rounded-lg p-4 border border-border"
        :class="{ 'opacity-50': !p.is_enabled }">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm font-medium text-text-primary">{{ p.name }}</div>
            <div v-if="p.description" class="text-xs text-text-secondary mt-0.5">{{ p.description }}</div>
            <div class="text-xs text-text-secondary mt-1">v{{ p.version }} · {{ p.entry_point }}</div>
          </div>
          <div class="flex items-center gap-2">
            <button v-if="p.is_enabled" @click="store.disable(p.id)"
              class="p-1.5 rounded hover:bg-surface-hover text-accent" title="Disable">
              <PowerOff :size="16" />
            </button>
            <button v-else @click="store.enable(p.id)"
              class="p-1.5 rounded hover:bg-surface-hover text-text-secondary" title="Enable">
              <Power :size="16" />
            </button>
            <button @click="store.uninstall(p.id)" class="p-1.5 rounded hover:bg-red-500/10 text-red-400" title="Uninstall">
              <Trash2 :size="16" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
