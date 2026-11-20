import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { callAiTool } from '../api/ai'
import { useAiTools } from './useAiTools'

/**
 * The apply paths splice at offsets captured when the request fired. A local
 * model can take minutes, so the anchor text must still be there when the
 * result lands — these tests pin the stale-offset guard and the happy path.
 */

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }))

vi.mock('../api/ai', () => ({ callAiTool: vi.fn() }))
vi.mock('../stores/toast', () => ({
  useToastStore: vi.fn(() => ({ error: toastError })),
}))
vi.mock('./aiToolRegistry', async (importOriginal) => ({
  ...(await importOriginal()),
  // Pulls the entries store — not needed here, and pinia isn't installed.
  currentEntryContext: () => null,
}))

const mockedCall = vi.mocked(callAiTool)

/** A runAiTool call whose result we resolve manually, simulating a slow model. */
function makeDeferredResult() {
  let resolve!: (result: { text: string }) => void
  mockedCall.mockReturnValue(
    new Promise((r) => {
      resolve = r
    }) as unknown as ReturnType<typeof callAiTool>,
  )
  return (text: string) => resolve({ text, suggestions: [] })
}

function makeTools(bodyText: string) {
  const body = ref(bodyText)
  const sel = { start: 0, end: 5 } // "hello"
  const applied: string[] = []
  const tools = useAiTools(
    body,
    () => body.value.slice(sel.start, sel.end),
    (text) => {
      applied.push(text)
      body.value =
        body.value.slice(0, sel.start) + text + body.value.slice(sel.end)
    },
    ref(sel.start),
    ref(sel.end),
    ref(null),
    () => {},
    () => {},
  )
  return { body, sel, applied, tools }
}

beforeEach(() => {
  mockedCall.mockReset()
  toastError.mockClear()
})

describe('useAiTools stale-anchor guard', () => {
  it('replace splices at the captured offsets when the text is unchanged', async () => {
    const deliver = makeDeferredResult()
    const { body, applied, tools } = makeTools('hello world')
    void tools.runAiTool('grammar')
    deliver('HELLO')
    await vi.waitFor(() => expect(tools.aiResult.value).toBe('HELLO'))

    tools.aiResultReplace()
    expect(body.value).toBe('HELLO world')
    expect(applied).toEqual(['HELLO'])
    expect(tools.aiResult.value).toBeNull()
  })

  it('replace refuses to splice when the body changed during the request', async () => {
    const deliver = makeDeferredResult()
    const { body, applied, tools } = makeTools('hello world')
    void tools.runAiTool('grammar')
    // The user keeps typing while the model runs — offsets now point elsewhere.
    body.value = 'dear diary, hello world'
    deliver('HELLO')
    await vi.waitFor(() => expect(tools.aiResult.value).toBe('HELLO'))

    tools.aiResultReplace()
    expect(body.value).toBe('dear diary, hello world') // untouched
    expect(applied).toEqual([])
    expect(tools.aiResult.value).toBe('HELLO') // result stays up for Copy
    expect(toastError).toHaveBeenCalledWith(
      'The text changed while the AI tool ran — reselect and try again.',
    )
  })

  it('insert lands after the selection when the text is unchanged', async () => {
    const deliver = makeDeferredResult()
    const { body, tools } = makeTools('hello world')
    void tools.runAiTool('continue')
    deliver(' there')
    await vi.waitFor(() => expect(tools.aiResult.value).toBe(' there'))

    tools.aiResultInsert()
    expect(body.value).toBe('hello\n there world')
    expect(tools.aiResult.value).toBeNull()
  })

  it('insert refuses when the insertion point moved during the request', async () => {
    const deliver = makeDeferredResult()
    const { body, tools } = makeTools('hello world')
    void tools.runAiTool('continue')
    body.value = 'dear diary, hello world'
    deliver(' there')
    await vi.waitFor(() => expect(tools.aiResult.value).toBe(' there'))

    tools.aiResultInsert()
    expect(body.value).toBe('dear diary, hello world')
    expect(tools.aiResult.value).toBe(' there')
    expect(toastError).toHaveBeenCalledWith(
      'The text changed while the AI tool ran — reselect and try again.',
    )
  })
})
