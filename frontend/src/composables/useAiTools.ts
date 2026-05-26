import { ref, type Ref } from 'vue'
import { grammarCheck, spellCheck, rewrite, continueWriting, summarize, expand, changeTone, translate } from '../api/ai'

export type AiToolMode = 'grammar' | 'spelling' | 'rewrite' | 'continue' | 'summarize' | 'expand' | 'tone' | 'translate'

export type AiToneStyle = 'formal' | 'professional' | 'casual' | 'friendly' | 'concise' | 'poetic'

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
  const aiResultMode = ref<AiToolMode | null>(null)
  const aiOriginalText = ref('')
  const aiOriginalStart = ref(0)
  const aiOriginalEnd = ref(0)
  const aiToneStyle = ref<AiToneStyle>('formal')

  function errMsg(e: unknown) { return e instanceof Error ? e.message : String(e) }

  async function runAiTool(mode: AiToolMode, toneOverride?: AiToneStyle) {
    const selectedText = getSelection()
    const needsSelection = mode !== 'continue'
    if (needsSelection && !selectedText) return

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

    // Apply tone override if provided
    if (toneOverride) aiToneStyle.value = toneOverride

    aiLoading.value = true
    aiResultMode.value = mode
    aiToolActive.value = mode
    // Keep previous result visible during retry — clear only after new result arrives
    try {
      let result = ''
      switch (mode) {
        case 'grammar': {
          const res = await grammarCheck(selectedText)
          result = res.corrected_text
          break
        }
        case 'spelling': {
          const res = await spellCheck(selectedText)
          result = res.corrected_text
          break
        }
        case 'rewrite': {
          const res = await rewrite(selectedText, aiToneStyle.value)
          result = res.rewritten_text
          break
        }
        case 'continue': {
          const text = selectedText || body.value
          if (!text.trim()) { aiLoading.value = false; aiToolActive.value = null; return }
          const res = await continueWriting(text)
          result = selectedText ? selectedText + res.continuation : res.continuation
          if (!selectedText) {
            aiOriginalStart.value = body.value.length
            aiOriginalEnd.value = body.value.length
          }
          break
        }
        case 'summarize': {
          const res = await summarize(selectedText)
          result = res.summary
          break
        }
        case 'expand': {
          const res = await expand(selectedText)
          result = res.expanded_text
          break
        }
        case 'tone': {
          const res = await changeTone(selectedText, aiToneStyle.value)
          result = res.rewritten_text
          break
        }
        case 'translate': {
          const res = await translate(selectedText, 'Spanish')
          result = res.translated_text
          break
        }
      }
      if (result) {
        aiResult.value = result
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
    // Don't clear result — keep panel open, loading state overlays the old result
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

  function applyToneStyle(tone: AiToneStyle) {
    const mode = aiResultMode.value
    if (!mode) return
    runAiTool(mode, tone)
  }

  return {
    aiLoading, aiToolActive, aiResult, aiResultMode,
    aiOriginalText, aiOriginalStart, aiOriginalEnd,
    aiToneStyle,
    runAiTool, aiResultReplace, aiResultInsert, aiResultRetry, aiResultCopy, applyToneStyle, clearAiResult,
  }
}
