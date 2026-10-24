import { describe, expect, it } from 'vitest'
import { mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import EditorToolbar from './EditorToolbar.vue'

/**
 * EditorToolbar — accessibility + wiring guard.
 *
 * The toolbar is presentational (props in, `@action(name)` out), so the
 * interesting assertions are: it mounts in both editor modes, every control
 * exposes an accessible name (the icon-only buttons carry `aria-label`), and a
 * click on a formatting button emits the matching `action`.
 */

const PROPS = {
  activeFormats: new Set<string>(),
  undoCount: 0,
  redoCount: 0,
  showEmoji: false,
  showFind: false,
  ui: {} as never,
}

function mountToolbar(mode: 'journal' | 'notes', extra: Record<string, unknown> = {}) {
  return mount(EditorToolbar, {
    props: { mode, ...PROPS, ...extra },
    global: { plugins: [createPinia()] },
  })
}

/** A button is nameable when it has an aria-label or non-empty text content. */
function accessibleName(button: DOMWrapper<Element>): string {
  const el = button.element as HTMLElement
  return (
    el.getAttribute('aria-label') ??
    el.getAttribute('title') ??
    button.text().trim()
  )
}

describe('EditorToolbar', () => {
  it('mounts in journal mode with named toolbar rows', async () => {
    const wrapper = mountToolbar('journal')
    expect(wrapper.element).toBeTruthy()

    const rows = wrapper.findAll('[role="toolbar"]')
    expect(rows.length).toBe(3)
    for (const row of rows) expect(row.attributes('aria-label')).toBeTruthy()
    wrapper.unmount()
  })

  it('mounts in notes mode with named toolbar rows', async () => {
    const wrapper = mountToolbar('notes', { isDesktop: true })
    expect(wrapper.element).toBeTruthy()

    const rows = wrapper.findAll('[role="toolbar"]')
    expect(rows.length).toBe(2)
    for (const row of rows) expect(row.attributes('aria-label')).toBeTruthy()
    wrapper.unmount()
  })

  it('gives every button an accessible name', async () => {
    for (const mode of ['journal', 'notes'] as const) {
      const wrapper = mountToolbar(mode, { isDesktop: true })
      const buttons = wrapper.findAll('button')
      expect(buttons.length).toBeGreaterThan(0)

      const unnamed = buttons.filter((b) => accessibleName(b) === '')
      expect(unnamed.map((b) => b.html())).toEqual([])

      // No icon-only button may rely on its tooltip alone for its name.
      for (const b of buttons) {
        expect(b.attributes('aria-label')).toBeTruthy()
      }
      wrapper.unmount()
    }
  })

  it('emits action when a formatting button is clicked', async () => {
    const wrapper = mountToolbar('journal')
    await wrapper.find('button[aria-label="Bold (Ctrl+B)"]').trigger('click')

    expect(wrapper.emitted('action')).toEqual([['bold']])
    wrapper.unmount()
  })

  it('emits action from the notes-only insert tools', async () => {
    const wrapper = mountToolbar('notes', { isDesktop: true })
    await wrapper
      .find('button[aria-label="Clip web page"]')
      .trigger('click')

    expect(wrapper.emitted('action')).toEqual([['clipWeb']])
    wrapper.unmount()
  })

  it('emits quickEmoji from the journal quick-insert row', async () => {
    const wrapper = mountToolbar('journal')
    await wrapper
      .find('button[aria-label="Insert 📝"]')
      .trigger('click')

    expect(wrapper.emitted('quickEmoji')).toEqual([['📝']])
    wrapper.unmount()
  })
})
