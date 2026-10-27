import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EditorStatusBar from './EditorStatusBar.vue'
import type { SaveState } from '../../composables/useAutoSave'

const saveState: SaveState = 'saved'

function mountBar(props: Record<string, unknown> = {}) {
  return mount(EditorStatusBar, {
    props: { words: 5, saveState, hasContent: true, ...props },
  })
}

describe('EditorStatusBar daily goal chip', () => {
  it('hides the goal chip when no daily prop is given (goal off)', () => {
    const wrapper = mountBar()
    expect(wrapper.text()).not.toContain('today:')
    // §9 ED7: word count is shown; char/line/paragraph/read-time are not.
    expect(wrapper.text()).toContain('5 words')
    expect(wrapper.text()).not.toContain('chars')
    expect(wrapper.text()).not.toContain('lines')
    expect(wrapper.text()).not.toContain('paragraphs')
    expect(wrapper.text()).not.toContain('min read')
  })

  it('shows today vs goal below the goal', () => {
    const wrapper = mountBar({ daily: { words: 120, goal: 500 } })
    expect(wrapper.text()).toContain('today: 120 / 500')
    // Scoped to the chip (the save-state "Saved" text is also green).
    expect(wrapper.find('span[title*="Goal"]').classes()).not.toContain(
      'text-green-500',
    )
  })

  it('turns green with a check once the goal is met', () => {
    const wrapper = mountBar({ daily: { words: 500, goal: 500 } })
    expect(wrapper.text()).toContain('today: 500 / 500')
    expect(wrapper.find('span[title*="Goal"]').classes()).toContain(
      'text-green-500',
    )
  })
})
