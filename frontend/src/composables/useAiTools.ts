import { ref, type Ref } from 'vue'
import { grammarCheck, rewrite, summarize, expand, changeTone, translate, analyzeText, defineText } from '../api/ai'

export type AiToolMode = 'grammar-spelling' | 'rewrite' | 'summarize' | 'expand' | 'tone' | 'translate' | 'analysis' | 'define'

export type AiToneStyle = 'formal' | 'casual' | 'friendly' | 'professional' | 'emphatic' | 'humorous' | 'poetic'

export const AI_TONE_OPTIONS: AiToneStyle[] = ['formal', 'casual', 'friendly', 'professional', 'emphatic', 'humorous', 'poetic']

export const AI_TRANSLATE_LANGUAGES = [
  'english', 'spanish', 'french', 'german', 'portuguese',
  'japanese', 'korean', 'chinese', 'arabic', 'hindi',
  'tamil', 'malayalam',
]

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
  const aiTranslateLanguage = ref('tamil')
  const aiAnalysisResult = ref<{ emotions: string[]; themes: string[]; summary: string } | null>(null)

  function errMsg(e: unknown) { return e instanceof Error ? e.message : String(e) }

  async function runAiTool(mode: AiToolMode, toneOverride?: AiToneStyle, languageOverride?: string) {
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

    // Apply overrides if provided
    if (toneOverride) aiToneStyle.value = toneOverride
    if (languageOverride) aiTranslateLanguage.value = languageOverride

    aiLoading.value = true
    aiResultMode.value = mode
    aiToolActive.value = mode
    aiAnalysisResult.value = null

    try {
      let result = ''
      switch (mode) {
        case 'grammar-spelling': {
          const res = await grammarCheck(selectedText)
          result = res.corrected_text
          break
        }
        case 'rewrite': {
          const res = await rewrite(selectedText, aiToneStyle.value)
          result = res.rewritten_text
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
          result = res.changed_text
          break
        }
        case 'translate': {
          const res = await translate(selectedText, aiTranslateLanguage.value)
          result = res.translated_text
          break
        }
        case 'analysis': {
          const res = await analyzeText(selectedText)
          aiAnalysisResult.value = res
          // Format for display in result panel
          const emotionStr = res.emotions.length ? res.emotions.join(', ') : 'None detected'
          const themeStr = res.themes.length ? res.themes.join(', ') : 'None detected'
          result = `Emotions: ${emotionStr}\n\nThemes: ${themeStr}\n\nSummary: ${res.summary}`
          break
        }
        case 'define': {
          const res = await defineText(selectedText)
          result = res.definition
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
    aiAnalysisResult.value = null
  }

  function applyToneStyle(tone: AiToneStyle) {
    const mode = aiResultMode.value
    if (!mode) return
    runAiTool(mode, tone)
  }

  function applyTranslateLanguage(language: string) {
    const mode = aiResultMode.value
    if (!mode) return
    runAiTool(mode, undefined, language)
  }

  return {
    aiLoading, aiToolActive, aiResult, aiResultMode,
    aiOriginalText, aiOriginalStart, aiOriginalEnd,
    aiToneStyle, aiTranslateLanguage, aiAnalysisResult,
    runAiTool, aiResultReplace, aiResultInsert, aiResultRetry, aiResultCopy, applyToneStyle, applyTranslateLanguage, clearAiResult,
  }
}
