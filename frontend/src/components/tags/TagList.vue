<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useTagsStore } from '../../stores/tags'
import { Plus, X, Search } from 'lucide-vue-next'

const props = defineProps<{ modelValue: number[] }>()
const emit = defineEmits<{ 'update:modelValue': [ids: number[]] }>()
const tags = useTagsStore()

const query = ref('')

onMounted(() => tags.fetchTree())

const q = computed(() => query.value.trim().toLowerCase())
const filtered = computed(() => {
  if (!q.value) return tags.tags
  return tags.tags.filter((t) => t.name.toLowerCase().includes(q.value))
})
const exactMatch = computed(() =>
  q.value ? tags.tags.some((t) => t.name.toLowerCase() === q.value) : false,
)
const canCreate = computed(() => q.value.length > 0 && !exactMatch)

function toggle(id: number) {
  const next = props.modelValue.includes(id)
    ? props.modelValue.filter((t) => t !== id)
    : [...props.modelValue, id]
  emit('update:modelValue', next)
}

/** Enter on the input: toggle an exact match, otherwise create a new tag. */
async function commit() {
  const name = query.value.trim()
  if (!name) return
  const existing = tags.tags.find((t) => t.name.toLowerCase() === q.value)
  if (existing) {
    if (!props.modelValue.includes(existing.id)) toggle(existing.id)
  } else {
    const tag = await tags.createTag({ name })
    emit('update:modelValue', [...props.modelValue, tag.id])
  }
  query.value = ''
}
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <!-- Typeahead search -->
    <div
      class="flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-hover border border-border focus-within:border-accent transition-colors"
    >
      <Search :size="11" class="text-text-muted shrink-0" aria-hidden="true" />
      <input
        v-model="query"
        class="flex-1 min-w-[6rem] bg-transparent text-xs text-text-primary outline-none placeholder-text-muted"
        placeholder="Find or add a tag…"
        @keydown.enter.prevent="commit"
        @keydown.escape="query = ''"
      />
      <button
        v-if="query"
        @click="query = ''"
        class="text-text-muted hover:text-text-primary cursor-pointer shrink-0"
        aria-label="Clear"
      >
        <X :size="11" />
      </button>
    </div>

    <!-- Matching tag pills -->
    <div
      v-if="filtered.length"
      class="flex flex-wrap items-center gap-1.5 max-h-32 overflow-y-auto"
    >
      <button
        v-for="tag in filtered"
        :key="tag.id"
        class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium cursor-pointer transition-colors"
        :class="
          modelValue.includes(tag.id)
            ? 'bg-tag-chip text-white'
            : 'bg-surface-hover text-text-secondary hover:text-text-primary'
        "
        @click="toggle(tag.id)"
      >
        {{ tag.name }}
      </button>
    </div>
    <p v-else-if="q" class="text-[11px] text-text-muted px-1">No matching tags.</p>

    <!-- Create-if-missing -->
    <button
      v-if="canCreate"
      class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs text-accent hover:bg-accent/10 cursor-pointer transition-colors w-fit"
      @click="commit"
    >
      <Plus :size="12" /> Create “{{ query.trim() }}”
    </button>
  </div>
</template>
