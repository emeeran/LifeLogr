<script setup lang="ts">
import type { Component, Ref } from "vue";
import { inject, computed } from "vue";

const props = defineProps<{
  title: string;
  icon?: Component;
  description?: string;
  resetLabel?: string;
  cardClass?: string;
  /** Optional key matched against the settings-search highlight. When it
   *  equals the active highlight, the section card briefly pulses. */
  settingKey?: string;
}>();

const emit = defineEmits<{
  reset: [];
}>();

const highlight = inject<Ref<string | null> | undefined>(
  "settings-highlight",
  undefined,
);
const isHighlighted = computed(
  () =>
    !!highlight && !!props.settingKey && highlight.value === props.settingKey,
);
</script>

<template>
  <section>
    <div class="flex items-start justify-between mb-1.5">
      <div class="flex items-start gap-2">
        <component
          v-if="icon"
          :is="icon"
          :size="14"
          class="text-accent shrink-0 mt-0.5"
          aria-hidden="true"
        />
        <div>
          <h3
            class="text-[13px] font-semibold text-text-primary tracking-tight flex items-center gap-1.5"
          >
            {{ title }}
          </h3>
          <p v-if="description" class="text-[11px] text-text-muted mt-0.5">
            {{ description }}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2 shrink-0 pt-0.5">
        <slot name="actions" />
        <button
          v-if="resetLabel"
          @click="emit('reset')"
          class="text-[11px] text-text-muted hover:text-accent cursor-pointer transition-colors"
        >
          {{ resetLabel }}
        </button>
      </div>
    </div>
    <div
      class="bg-surface rounded-md border border-border transition-shadow"
      :class="[
        cardClass ?? 'p-2.5 space-y-1.5',
        isHighlighted ? 'settings-highlight' : '',
      ]"
      :data-setting-key="settingKey"
    >
      <slot />
    </div>
  </section>
</template>
