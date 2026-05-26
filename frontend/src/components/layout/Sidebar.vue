<script setup lang="ts">
import { useUiStore, type ViewType } from '../../stores/ui'
import {
  Calendar, Clock, Search, Sunrise, Settings,
  Sun, Moon, BarChart3, MapPin, Bell,
  ChevronsLeft, ChevronsRight, BookOpen, StickyNote
} from 'lucide-vue-next'
import type { Component } from 'vue'

const ui = useUiStore()

const navItems: { view: ViewType; icon: Component; label: string }[] = [
  { view: 'calendar', icon: Calendar, label: 'Calendar' },
  { view: 'timeline', icon: Clock, label: 'Timeline' },
  { view: 'search', icon: Search, label: 'Search' },
  { view: 'analytics', icon: BarChart3, label: 'Analytics' },
  { view: 'digest', icon: BookOpen, label: 'Digest' },
  { view: 'map', icon: MapPin, label: 'Map' },
  { view: 'reminders', icon: Bell, label: 'Reminders' },
  { view: 'on-this-day', icon: Sunrise, label: 'On this day' },
]

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
        <img src="/logo.png" alt="DailyByte" role="button" tabindex="0" class="shrink-0 cursor-pointer logo-icon w-7 h-7" @click="ui.toggleSidebar()" @keydown.enter="ui.toggleSidebar()" />
      </div>
      <template v-else>
        <img src="/logo.png" alt="DailyByte" role="button" tabindex="0" class="shrink-0 cursor-pointer logo-icon w-5 h-5" @click="ui.toggleSidebar()" @keydown.enter="ui.toggleSidebar()" />
        <div class="flex flex-col min-w-0">
          <span class="text-sm font-bold text-sidebar-text tracking-tight leading-tight">DailyByte</span>
          <span class="text-[8px] text-sidebar-text-secondary leading-tight">Your Day in Media & Minutes</span>
        </div>
      </template>
    </div>

    <!-- Scrollable nav -->
    <div class="flex-1 py-1" :class="ui.sidebarCollapsed ? 'overflow-y-hidden' : 'overflow-y-auto'">
      <router-link
        v-for="item in navItems"
        :key="item.view"
        :to="`/${item.view === 'calendar' ? '' : item.view}`"
        class="flex items-center gap-2 text-xs cursor-pointer transition-colors duration-150"
        :class="[
          ui.sidebarCollapsed ? 'justify-center px-1 py-2' : 'px-3 py-1.5',
          isActive(item.view)
            ? 'bg-sidebar-hover text-sidebar-text border-r-2 border-white/60'
            : 'text-sidebar-text-secondary hover:bg-sidebar-hover hover:text-sidebar-text'
        ]"
        :title="ui.sidebarCollapsed ? item.label : undefined"
        :aria-label="item.label"
        :aria-current="isActive(item.view) ? 'page' : undefined"
        @click="navigate(item.view)"
      >
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
