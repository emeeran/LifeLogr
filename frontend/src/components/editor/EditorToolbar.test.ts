import { describe, expect, it } from 'vitest'
import { mount, type DOMWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import EditorToolbar from './EditorToolbar.vue'

/**
 * EditorToolbar — accessibility + wiring guard, plus the spec §9 ED1–ED5
 * toolbar item-set contract.
 *
 * The toolbar is presentational (props in, `@action(name)` out). §9 requires
 * one heading set (H1–H4 + paragraph) in BOTH editors (ED1), no alignment
 * group (ED2), no table/hr buttons — they live in the context menu (ED3), no
 * emoji shortcut row — the shared picker is the only emoji surface (ED4), and
 * exactly one font-family / one font-size dropdown (ED5).
 */

const PROPS = {
  activeFormats: new Set<string>(),
  undoCount: 0,
  redoCount: 0,
  showEmoji: false,
  showFind: false,
  ui: {} as never,
}

function mountToolbar(
  mode: 'journal' | 'notes',
  extra: Record<string, unknown> = {},
) {
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

const HEADING_TITLES = [
  'Heading 1',
  'Heading 2',
  'Heading 3',
  'Heading 4',
  'Paragraph (remove heading)',
]
const BANNED_TITLES = [
  'Align left',
  'Align center',
  'Align right',
  'Align justify',
  'Table',
  'Horizontal rule',
]

describe('EditorToolbar', () => {
  it('mounts in journal mode with named toolbar rows', () => {
    const wrapper = mountToolbar('journal')
    expect(wrapper.element).toBeTruthy()

    const rows = wrapper.findAll('[role="toolbar"]')
    // ED4 removed the quick-emoji row — both modes now have the same two rows.
    expect(rows.length).toBe(2)
    for (const row of rows) expect(row.attributes('aria-label')).toBeTruthy()
    wrapper.unmount()
  })

  it('mounts in notes mode with named toolbar rows', () => {
    const wrapper = mountToolbar('notes', { isDesktop: true })
    expect(wrapper.element).toBeTruthy()

    const rows = wrapper.findAll('[role="toolbar"]')
    expect(rows.length).toBe(2)
    for (const row of rows) expect(row.attributes('aria-label')).toBeTruthy()
    wrapper.unmount()
  })

  it('gives every button an accessible name', () => {
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

  // ── spec §9 ED1–ED5: the toolbar item set ──
  for (const mode of ['journal', 'notes'] as const) {
    it(`${mode}: shows the full heading set and no alignment/table/hr buttons`, () => {
      const wrapper = mountToolbar(mode)
      const titles = wrapper
        .findAll('button')
        .map((b) => b.attributes('title'))
      for (const t of HEADING_TITLES) expect(titles).toContain(t)
      for (const t of BANNED_TITLES) expect(titles).not.toContain(t)
      wrapper.unmount()
    })

    it(`${mode}: has one font-family and one font-size dropdown`, () => {
      const wrapper = mountToolbar(mode)
      const selects = wrapper.findAll('select')
      expect(selects).toHaveLength(2)
      expect(selects[0].attributes('aria-label')).toBe('Font family')
      expect(selects[1].attributes('aria-label')).toBe('Font size')
      wrapper.unmount()
    })
  }

  it('emits action when a formatting button is clicked', async () => {
    const wrapper = mountToolbar('journal')
    await wrapper.find('button[aria-label="Bold (Ctrl+B)"]').trigger('click')

    expect(wrapper.emitted('action')).toEqual([['bold']])
    wrapper.unmount()
  })

  it('emits action from the notes-only insert tools', async () => {
    const wrapper = mountToolbar('notes', { isDesktop: true })
    await wrapper.find('button[aria-label="Clip web page"]').trigger('click')

    expect(wrapper.emitted('action')).toEqual([['clipWeb']])
    wrapper.unmount()
  })
})
