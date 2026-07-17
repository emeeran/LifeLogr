<script setup lang="ts">
/**
 * SettingGroup — a labelled sub-grouping inside a SettingsSection.
 *
 * Replaces the ad-hoc `border-t border-border pt-2` dividers sprinkled
 * inline to separate conceptual blocks (e.g. Connection / Models /
 * Features in the AI tab). Gives every section a consistent grouping
 * rhythm with an optional uppercase eyebrow label.
 */
defineProps<{
  /** Optional uppercase eyebrow label above the group. */
  label?: string;
}>();
</script>

<template>
  <div
    class="border-t border-border first:border-t-0 first:pt-0 pt-2 space-y-1.5"
  >
    <p
      v-if="label"
      class="text-[10px] text-text-muted uppercase tracking-wide font-medium"
    >
      {{ label }}
    </p>
    <slot />
  </div>
</template>
