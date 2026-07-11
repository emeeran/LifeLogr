<script setup lang="ts">
/** PlannerView — unified Tasks + Schedule module with tabbed layout. */
import { ref } from 'vue'
import { ListTodo, CalendarDays } from 'lucide-vue-next'
import TaskPanel from './TaskPanel.vue'
import SchedulePanel from './SchedulePanel.vue'

const tab = ref<'tasks' | 'schedule'>('tasks')
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between gap-3 px-6 pt-5 pb-3 border-b border-border">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
          <ListTodo :size="20" class="text-accent" />
        </div>
        <div>
          <h1 class="text-xl font-bold text-text-primary leading-tight">Planner</h1>
          <p class="text-[11px] text-text-muted">Tasks and schedule, all in one place</p>
        </div>
      </div>
      <!-- Tabs -->
      <div class="flex items-center gap-1 bg-surface-hover rounded-lg p-1 border border-border">
        <button @click="tab = 'tasks'"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors cursor-pointer"
          :class="tab === 'tasks' ? 'bg-accent text-white shadow-sm' : 'text-text-secondary hover:text-text-primary'">
          <ListTodo :size="13" /> Tasks
        </button>
        <button @click="tab = 'schedule'"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-md transition-colors cursor-pointer"
          :class="tab === 'schedule' ? 'bg-accent text-white shadow-sm' : 'text-text-secondary hover:text-text-primary'">
          <CalendarDays :size="13" /> Schedule
        </button>
      </div>
    </div>

    <!-- Body -->
    <div class="flex-1 overflow-hidden">
      <TaskPanel v-show="tab === 'tasks'" />
      <SchedulePanel v-show="tab === 'schedule'" />
    </div>
  </div>
</template>
