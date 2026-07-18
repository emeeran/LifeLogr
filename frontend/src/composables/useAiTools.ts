import { ref, type Ref } from 'vue'
import { errMsg } from '../utils/error'
import { callAiTool } from '../api/ai'
import { AI_TOOL_BY_ID } from './aiToolRegistry'

// Re-exported so existing imports from this module keep resolving.
export type { AiToolMode, AiToneStyle } from './aiToolRegistry'

export function useAiTools(
  body: Ref<string>,
  getSelection: () => string,
  applyToSelection: (text: string) => void,
  cachedSelStart: Ref<number>,
  cachedSelEnd: Ref<number>,
  textarea: Ref<HTMLTextAreaElement | null>,
  pushHistory: () => void,
  markDirty: () => void,
) {
  const aiLoading = ref(false)
  const aiToolActive = ref<string | null>(null)
  const aiResult = ref<string | null>(null)
  const aiResultMode = ref<string | null>(null)
  const aiOriginalText = ref('')
  const aiOriginalStart = ref(0)
  const aiOriginalEnd = ref(0)
  /** Current parameter value for the active tool (tone / voice / language…). */
  const aiParamValue = ref<string>('formal')

  async function runAiTool(mode: string, paramOverride?: string) {
    const def = AI_TOOL_BY_ID[mode]
    if (!def) return

    const selectedText = getSelection()
    if (!selectedText) return

    const el = textarea.value
    if (el) {
      const focused = document.activeElement === el
      aiOriginalStart.value = focused ? el.selectionStart : cachedSelStart.value
      aiOriginalEnd.value = focused ? el.selectionEnd : cachedSelEnd.value
    } else {
      aiOriginalStart.value = cachedSelStart.value
      aiOriginalEnd.value = cachedSelEnd.value
    }
    aiOriginalText.value = selectedText

    if (paramOverride !== undefined) {
      aiParamValue.value = paramOverride
    } else if (def.param) {
      aiParamValue.value = def.param.default
    }

    aiLoading.value = true
    aiResultMode.value = mode
    aiToolActive.value = mode

    try {
      const { text } = await callAiTool(def, selectedText, aiParamValue.value)
      if (text) {
        aiResult.value = text
      }
    } catch (e: unknown) {
      alert(`AI tool failed: ${errMsg(e)}`)
      aiResultMode.value = null
    } finally {
      aiLoading.value = false
      aiToolActive.value = null
    }
  }

  function aiResultReplace() {
    if (!aiResult.value) return
    if (aiOriginalText.value) {
      const el = textarea.value
      if (el) {
        el.focus()
        el.selectionStart = aiOriginalStart.value
        el.selectionEnd = aiOriginalEnd.value
      }
      applyToSelection(aiResult.value)
    } else {
      body.value += aiResult.value
      pushHistory()
      markDirty()
    }
    clearAiResult()
  }

  function aiResultInsert() {
    if (!aiResult.value) return
    const end = aiOriginalEnd.value
    body.value = body.value.slice(0, end) + '\n' + aiResult.value + body.value.slice(end)
    pushHistory()
    markDirty()
    clearAiResult()
  }

  function aiResultRetry() {
    const mode = aiResultMode.value
    if (!mode) return
    runAiTool(mode)
  }

  function aiResultCopy() {
    if (!aiResult.value) return
    navigator.clipboard.writeText(aiResult.value)
    clearAiResult()
  }

  function clearAiResult() {
    aiResult.value = null
    aiResultMode.value = null
    aiOriginalText.value = ''
  }

  function applyToolParam(value: string) {
    const mode = aiResultMode.value
    if (!mode) return
    runAiTool(mode, value)
  }

  return {
    aiLoading,
    aiToolActive,
    aiResult,
    aiResultMode,
    aiOriginalText,
    aiOriginalStart,
    aiOriginalEnd,
    aiParamValue,
    runAiTool,
    aiResultReplace,
    aiResultInsert,
    aiResultRetry,
    aiResultCopy,
    applyToolParam,
    clearAiResult,
  }
}
