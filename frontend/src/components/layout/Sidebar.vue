<script setup lang="ts">
import { computed, ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { useUiStore, type ViewType } from '../../stores/ui'
import {
  Calendar, Clock, Search, Sunrise, Settings,
  Sun, Moon, BarChart3, Bell, ImageIcon, Users, ListTodo, Mail,
  ChevronsLeft, ChevronsRight, StickyNote, NotebookPen, LayoutDashboard, GripVertical
} from 'lucide-vue-next'
import type { Component } from 'vue'

const ui = useUiStore()

const navItems: { view: ViewType; icon: Component; label: string }[] = [
  { view: 'dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { view: 'calendar', icon: Calendar, label: 'Calendar' },
  { view: 'timeline', icon: Clock, label: 'Timeline' },
  { view: 'notes', icon: NotebookPen, label: 'Notes' },
  { view: 'search', icon: Search, label: 'Search' },
  { view: 'analytics', icon: BarChart3, label: 'Analytics' },
  { view: 'reminders', icon: Bell, label: 'Reminders' },
  { view: 'planner', icon: ListTodo, label: 'Planner' },
  { view: 'contacts', icon: Users, label: 'Contacts' },
  { view: 'email', icon: Mail, label: 'Email' },
  { view: 'media', icon: ImageIcon, label: 'Media' },
  { view: 'on-this-day', icon: Sunrise, label: 'On this day' },
]

// User-customisable nav order (persisted). Drag a nav item to reorder.
const savedOrder = useLocalStorage<string[]>('lifelogr-nav-order', [])
const orderedNav = computed(() => {
  if (!savedOrder.value.length) return navItems
  const byView = new Map(navItems.map((i) => [i.view, i]))
  const ordered = savedOrder.value
    .map((v) => byView.get(v as ViewType))
    .filter((i): i is (typeof navItems)[number] => Boolean(i))
  // Append any views added since the order was saved.
  for (const item of navItems) {
    if (!savedOrder.value.includes(item.view)) ordered.push(item)
  }
  return ordered
})

// HTML5 drag-and-drop state.
const dragIndex = ref<number | null>(null)
const dropIndex = ref<number | null>(null)
// "Edit layout" mode pins the drag handles visible + shows a reorder hint.
const editMode = ref(false)

function onDragStart(_e: DragEvent, i: number) {
  dragIndex.value = i
}
function onDragOver(e: DragEvent, i: number) {
  // Allow drop; track the item we're hovering for the insertion indicator.
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  if (dragIndex.value !== null && i !== dragIndex.value) dropIndex.value = i
}
function onDrop(e: DragEvent, i: number) {
  e.preventDefault()
  const from = dragIndex.value
  if (from !== null && from !== i) {
    const views = orderedNav.value.map((n) => n.view)
    const [moved] = views.splice(from, 1)
    views.splice(i, 0, moved)
    savedOrder.value = views
  }
  dragIndex.value = null
  dropIndex.value = null
}
function onDragEnd() {
  dragIndex.value = null
  dropIndex.value = null
}

function isActive(view: ViewType) {
  return ui.activeView === view
}

function navigate(view: ViewType) {
  ui.setView(view)
}
</script>

<template>
  <nav class="h-full bg-sidebar flex flex-col border-r border-sidebar-hover transition-all duration-200 overflow-hidden"
    :style="{ width: ui.sidebarCollapsed ? '48px' : '200px' }">
    <!-- Brand -->
    <div class="border-b border-sidebar-hover shrink-0"
      :class="ui.sidebarCollapsed ? 'flex justify-center px-1 py-2.5' : 'flex items-center gap-1.5 px-3 py-2.5'">
      <div v-if="ui.sidebarCollapsed" class="flex flex-col items-center gap-0.5">
        <img src="/logo.png" alt="LifeLogr" role="button" tabindex="0" class="shrink-0 cursor-pointer logo-icon w-7 h-7" @click="ui.toggleSidebar()" @keydown.enter="ui.toggleSidebar()" />
      </div>
      <template v-else>
        <img src="/logo.png" alt="LifeLogr" role="button" tabindex="0" class="shrink-0 cursor-pointer logo-icon w-5 h-5" @click="ui.toggleSidebar()" @keydown.enter="ui.toggleSidebar()" />
        <div class="flex flex-col min-w-0">
          <span class="text-sm font-bold text-sidebar-text tracking-tight leading-tight">LifeLogr</span>
          <span class="text-[8px] text-sidebar-text-secondary leading-tight">Your Day in Media & Minutes</span>
        </div>
      </template>
    </div>

    <!-- Scrollable nav (drag to reorder) -->
    <div class="flex-1 py-1" :class="ui.sidebarCollapsed ? 'overflow-y-hidden' : 'overflow-y-auto'">
      <div
        v-if="editMode && !ui.sidebarCollapsed"
        class="mx-2 mb-1 px-2 py-1 rounded bg-sidebar-hover text-[10px] text-sidebar-text-secondary text-center"
      >
        Drag items to reorder
      </div>
      <router-link
        v-for="(item, index) in orderedNav"
        :key="item.view"
        :to="`/${item.view}`"
        draggable="true"
        class="group relative flex items-center gap-2 text-xs cursor-grab transition-colors duration-150 active:cursor-grabbing"
        :class="[
          ui.sidebarCollapsed ? 'justify-center px-1 py-2' : 'px-3 py-1.5',
          isActive(item.view)
            ? 'bg-sidebar-hover text-sidebar-text border-r-2 border-white/60'
            : 'text-sidebar-text-secondary hover:bg-sidebar-hover hover:text-sidebar-text',
          dragIndex === index ? 'opacity-40' : '',
          dropIndex === index ? 'shadow-[inset_0_2px_0_0_var(--color-accent)]' : '',
        ]"
        :title="ui.sidebarCollapsed ? item.label : undefined"
        :aria-label="item.label"
        :aria-current="isActive(item.view) ? 'page' : undefined"
        @click="navigate(item.view)"
        @dragstart="onDragStart($event, index)"
        @dragover="onDragOver($event, index)"
        @drop="onDrop($event, index)"
        @dragend="onDragEnd"
      >
        <GripVertical
          v-if="!ui.sidebarCollapsed"
          :size="12"
          class="drag-grip shrink-0 transition-opacity duration-150"
          :class="editMode ? 'opacity-80' : 'opacity-0 group-hover:opacity-50'"
        />
        <component :is="item.icon" :size="14" />
        <span v-if="!ui.sidebarCollapsed">{{ item.label }}</span>
      </router-link>
    </div>

    <!-- Scribble pad toggle -->
    <div class="border-t border-sidebar-hover py-1">
      <button
        class="flex items-center gap-2 w-full text-xs text-sidebar-text-secondary hover:bg-sidebar-hover hover:text-sidebar-text cursor-pointer transition-colors duration-150"
        :class="[
          ui.sidebarCollapsed ? 'justify-center px-1 py-2' : 'px-3 py-1.5',
          ui.scribbleOpen ? 'bg-sidebar-hover text-sidebar-text' : ''
        ]"
        :title="ui.sidebarCollapsed ? 'Scribble Pad' : undefined"
        aria-label="Toggle Scribble Pad"
        @click="ui.toggleScribble()"
      >
        <StickyNote :size="14" />
        <span v-if="!ui.sidebarCollapsed">Scribble</span>
      </button>
    </div>

    <!-- Bottom: theme + settings + collapse -->
    <div class="border-t border-sidebar-hover py-1">
      <button
        v-if="!ui.sidebarCollapsed"
        class="flex items-center gap-2 w-full text-xs cursor-pointer transition-colors duration-150"
        :class="editMode
          ? 'bg-sidebar-hover text-sidebar-text'
          : 'text-sidebar-text-secondary hover:bg-sidebar-hover hover:text-sidebar-text'"
        aria-label="Edit navigation layout"
        @click="editMode = !editMode"
      >
        <GripVertical :size="14" class="drag-grip" />
        <span>{{ editMode ? 'Done' : 'Edit layout' }}</span>
      </button>
      <button
        class="flex items-center gap-2 w-full text-xs text-sidebar-text-secondary hover:bg-sidebar-hover hover:text-sidebar-text cursor-pointer transition-colors duration-150"
        :class="ui.sidebarCollapsed ? 'justify-center px-1 py-2' : 'px-3 py-1.5'"
        :title="ui.sidebarCollapsed ? (ui.darkMode ? 'Light mode' : 'Dark mode') : undefined"
        :aria-label="ui.darkMode ? 'Switch to light mode' : 'Switch to dark mode'"
        @click="ui.toggleTheme()"
      >
        <Sun v-if="ui.darkMode" :size="14" />
        <Moon v-else :size="14" />
        <span v-if="!ui.sidebarCollapsed">{{ ui.darkMode ? 'Light' : 'Dark' }}</span>
      </button>
      <router-link
        to="/settings"
        class="flex items-center gap-2 text-xs text-sidebar-text-secondary hover:bg-sidebar-hover hover:text-sidebar-text cursor-pointer transition-colors duration-150"
        :class="ui.sidebarCollapsed ? 'justify-center px-1 py-2' : 'px-3 py-1.5'"
        :title="ui.sidebarCollapsed ? 'Settings' : undefined"
        aria-label="Settings"
        @click="navigate('settings')"
      >
        <component :is="Settings" :size="14" />
        <span v-if="!ui.sidebarCollapsed">Settings</span>
      </router-link>
      <button
        class="flex items-center gap-2 w-full text-xs text-sidebar-text-muted hover:bg-sidebar-hover hover:text-sidebar-text cursor-pointer transition-colors duration-150"
        :class="ui.sidebarCollapsed ? 'justify-center px-1 py-2' : 'px-3 py-1.5'"
        :title="ui.sidebarCollapsed ? 'Expand' : 'Collapse'"
        :aria-label="ui.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @click="ui.toggleSidebar()"
      >
        <ChevronsRight v-if="ui.sidebarCollapsed" :size="14" />
        <ChevronsLeft v-else :size="14" />
        <span v-if="!ui.sidebarCollapsed">Collapse</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.logo-icon {
  filter: brightness(0) invert(1);
}
</style>
