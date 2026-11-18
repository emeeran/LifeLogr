import { ref, type Ref } from 'vue'
import { callAiTool } from '../api/ai'
import {
  AI_TOOL_BY_ID,
  currentEntryContext,
  truncateForAi,
  type AiTruncation,
} from './aiToolRegistry'
import { errorMessage } from '../utils/errorMessage'
import { useToastStore } from '../stores/toast'

// Re-exported so existing imports from this module keep resolving.
export type { AiToolMode, AiTruncation } from './aiToolRegistry'

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
  /** Current parameter value for the active tool (mode / language…). */
  const aiParamValue = ref<string>('')
  /** Non-null when the selection was cut to the backend limit (spec AI3). */
  const aiTruncation = ref<AiTruncation | null>(null)
  /** 0-based retry attempt; each retry bumps backend temperature (spec AI5). */
  const aiAttempt = ref(0)

  async function runAiTool(mode: string, paramOverride?: string, attempt = 0) {
    const def = AI_TOOL_BY_ID[mode]
    if (!def) return

    const selectedText = getSelection()
    if (!selectedText.trim()) {
      useToastStore().error('Select some text in the editor first.')
      return
    }
    // The AI schemas cap text at 50k — an over-long selection would come back
    // as a raw 422 validation toast; fail soft with a clear message instead.
    if (selectedText.length > 50_000) {
      useToastStore().error(
        'AI tools work on selections up to 50,000 characters — shorten the selection and try again.',
      )
      return
    }

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

    // Non-silent truncation (spec AI3): the notice is set BEFORE the request so
    // it is visible while the tool runs, not only with the result.
    const sent = truncateForAi(selectedText)
    aiTruncation.value = sent.truncation
    aiAttempt.value = attempt

    aiLoading.value = true
    aiResultMode.value = mode
    aiToolActive.value = mode

    try {
      const { text } = await callAiTool(def, sent.text, aiParamValue.value, {
        attempt,
        entryContext: currentEntryContext(),
      })
      if (text) {
        aiResult.value = text
      }
    } catch (e: unknown) {
      useToastStore().error(`AI tool failed: ${errorMessage(e)}`)
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
    body.value =
      body.value.slice(0, end) + '\n' + aiResult.value + body.value.slice(end)
    pushHistory()
    markDirty()
    clearAiResult()
  }

  function aiResultRetry() {
    const mode = aiResultMode.value
    if (!mode) return
    // Vary the request (spec AI5): next attempt raises the temperature.
    runAiTool(mode, undefined, aiAttempt.value + 1)
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
    aiTruncation.value = null
  }

  function applyToolParam(value: string) {
    const mode = aiResultMode.value
    if (!mode) return
    // A param change is a fresh request, not a retry — reset the attempt.
    runAiTool(mode, value, 0)
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
    aiTruncation,
    aiAttempt,
    runAiTool,
    aiResultReplace,
    aiResultInsert,
    aiResultRetry,
    aiResultCopy,
    applyToolParam,
    clearAiResult,
  }
}
