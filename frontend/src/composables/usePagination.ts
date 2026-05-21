import { ref, computed } from 'vue'

export function usePagination(defaultLimit = 20) {
  const offset = ref(0)
  const limit = ref(defaultLimit)
  const total = ref(0)

  const page = computed(() => Math.floor(offset.value / limit.value) + 1)
  const totalPages = computed(() => Math.ceil(total.value / limit.value))
  const hasNext = computed(() => offset.value + limit.value < total.value)
  const hasPrev = computed(() => offset.value > 0)

  function nextPage() {
    if (hasNext.value) offset.value += limit.value
  }

  function prevPage() {
    if (hasPrev.value) offset.value = Math.max(0, offset.value - limit.value)
  }

  function reset() {
    offset.value = 0
  }

  return { offset, limit, total, page, totalPages, hasNext, hasPrev, nextPage, prevPage, reset }
}
