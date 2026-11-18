<script setup lang="ts">
/**
 * VideoThumb — lazy first-frame thumbnail for a video attachment tile.
 *
 * A muted `<video preload="metadata">` decodes a frame inside the renderer
 * process; a timeline of these decoding at once pushed WebKitWebProcess into
 * the gigabytes. The element is only mounted once the tile approaches the
 * viewport (IntersectionObserver via @vueuse/core — the first screenful fires
 * immediately, everything else waits for scroll); until then a static icon
 * placeholder matching the tile's icon styling stands in.
 */
import { ref } from 'vue'
import { useIntersectionObserver } from '@vueuse/core'
import { Film } from 'lucide-vue-next'

const props = defineProps<{ src: string }>()

const root = ref<HTMLElement | null>(null)
const visible = ref(false)

// Ref sits on the placeholder: once `visible` flips, the placeholder (and the
// observation with it) is replaced by the real <video> — one-way upgrade.
useIntersectionObserver(
  root,
  ([entry]) => {
    if (entry?.isIntersecting) visible.value = true
  },
  { rootMargin: '300px' },
)
</script>

<template>
  <video
    v-if="visible"
    :src="props.src"
    muted
    preload="metadata"
    class="w-full h-full object-cover"
    @loadeddata="
      (e) =>
        ((e.target as HTMLVideoElement).currentTime = Math.min(
          0.1,
          (e.target as HTMLVideoElement).duration || 0,
        ))
    "
  />
  <div
    v-else
    ref="root"
    class="w-full h-full flex items-center justify-center bg-surface-hover text-text-muted"
  >
    <Film :size="20" class="text-accent/60" />
  </div>
</template>
