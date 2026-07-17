import { ref, computed, nextTick, type Ref } from 'vue'

export function useFindReplace(body: Ref<string>, textarea: Ref<HTMLTextAreaElement | null>, pushHistory: () => void) {
  const showFind = ref(false)
  const findQuery = ref('')
  const replaceQuery = ref('')
  const findIndex = ref(-1)
  const findCount = ref(0)

  const findMatches = computed(() => {
    if (!findQuery.value) { findIndex.value = -1; findCount.value = 0; return [] }
    const matches: number[] = []
    const q = findQuery.value.toLowerCase()
    const txt = body.value.toLowerCase()
    let i = -1
    while ((i = txt.indexOf(q, i + 1)) !== -1) matches.push(i)
    findCount.value = matches.length
    return matches
  })

  function jumpToMatch(dir: 1 | -1 = 1) {
    if (!findMatches.value.length) { findIndex.value = -1; return }
    if (findIndex.value === -1) { findIndex.value = 0 }
    else { findIndex.value = (findIndex.value + dir + findMatches.value.length) % findMatches.value.length }
    const pos = findMatches.value[findIndex.value]
    nextTick(() => {
      if (!textarea.value) return
      textarea.value.focus()
      textarea.value.selectionStart = pos
      textarea.value.selectionEnd = pos + findQuery.value.length
    })
  }

  function replaceOne() {
    if (findIndex.value < 0 || !findMatches.value.length) return
    const pos = findMatches.value[findIndex.value]
    body.value = body.value.slice(0, pos) + replaceQuery.value + body.value.slice(pos + findQuery.value.length)
    pushHistory()
    nextTick(() => jumpToMatch(1))
  }

  function replaceAll() {
    if (!findQuery.value) return
    body.value = body.value.split(findQuery.value).join(replaceQuery.value)
    pushHistory()
    findIndex.value = -1
  }

  return { showFind, findQuery, replaceQuery, findIndex, findCount, findMatches, jumpToMatch, replaceOne, replaceAll }
}
