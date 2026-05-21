<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useTagsStore } from '../../stores/tags'
import { Plus, X } from 'lucide-vue-next'

const props = defineProps<{ modelValue: number[] }>()
const emit = defineEmits<{ 'update:modelValue': [ids: number[]] }>()
const tags = useTagsStore()

const showInput = ref(false)
const newTagName = ref('')

onMounted(() => tags.fetchTree())

function toggle(id: number) {
  const next = props.modelValue.includes(id)
    ? props.modelValue.filter(t => t !== id)
    : [...props.modelValue, id]
  emit('update:modelValue', next)
}

async function addTag() {
  const name = newTagName.value.trim()
  if (!name) return
  const tag = await tags.createTag({ name })
  newTagName.value = ''
  showInput.value = false
  emit('update:modelValue', [...props.modelValue, tag.id])
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-1.5">
    <button
      v-for="tag in tags.tags"
      :key="tag.id"
      class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium cursor-pointer transition-colors"
      :class="modelValue.includes(tag.id)
        ? 'bg-tag-chip text-white'
        : 'bg-surface-hover text-text-secondary hover:text-text-primary'"
      @click="toggle(tag.id)"
    >
      {{ tag.name }}
    </button>

    <!-- Inline new tag input -->
    <div v-if="showInput" class="inline-flex items-center gap-1">
      <input
        v-model="newTagName"
        class="w-24 px-2 py-0.5 rounded-full text-xs bg-surface-hover border border-border text-text-primary outline-none focus:border-accent"
        placeholder="Tag name"
        @keydown.enter="addTag"
        @keydown.escape="showInput = false; newTagName = ''"
        autofocus
      />
      <button @click="showInput = false; newTagName = ''" class="text-text-muted hover:text-text-primary cursor-pointer"><X :size="12" /></button>
    </div>

    <!-- Add tag button -->
    <button
      v-else
      class="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs text-text-muted hover:text-accent hover:bg-accent/10 cursor-pointer transition-colors"
      @click="showInput = true"
      title="Create new tag"
    >
      <Plus :size="12" /> Tag
    </button>
  </div>
</template>
