import { describe, expect, it } from 'vitest'
import { AI_MAX_TEXT_CHARS, AI_TOOLS, AI_TOOL_BY_ID, truncateForAi } from './aiToolRegistry'

describe('aiToolRegistry (spec §10)', () => {
  it('presents at most 8 top-level tools with unique ids (AI4)', () => {
    expect(AI_TOOLS.length).toBeLessThanOrEqual(8)
    expect(new Set(AI_TOOLS.map((t) => t.id)).size).toBe(AI_TOOLS.length)
  })

  it('contains the folded contract set incl. rewrite modes and continue (AI4, AI6)', () => {
    expect(AI_TOOL_BY_ID['rewrite']?.param?.options).toEqual([
      'as-is',
      'polish',
      'clarity',
      'simplify',
      'formal',
      'casual',
    ])
    expect(AI_TOOL_BY_ID['summarize']?.param?.options).toEqual([
      'sentences',
      'bullets',
      'actions',
    ])
    expect(AI_TOOL_BY_ID['continue']?.endpoint).toBe('/ai/continue-writing')
    // define is dropped from the menu.
    expect(AI_TOOL_BY_ID['define']).toBeUndefined()
  })

  it('truncateForAi reports how much was sent (AI3)', () => {
    const short = truncateForAi('hello')
    expect(short).toEqual({ text: 'hello', truncation: null })

    const long = truncateForAi('x'.repeat(AI_MAX_TEXT_CHARS + 1234))
    expect(long.text.length).toBe(AI_MAX_TEXT_CHARS)
    expect(long.truncation).toEqual({ sent: AI_MAX_TEXT_CHARS, total: AI_MAX_TEXT_CHARS + 1234 })
  })
})
