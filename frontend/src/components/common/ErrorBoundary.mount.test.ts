/* eslint-disable vue/one-component-per-file -- throwaway crash components */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ErrorBoundary from './ErrorBoundary.vue'

/**
 * A crashing view must show a recoverable panel, not an empty main area — the
 * "screen goes blank" report. This also pins that the failure is reported to
 * the backend once, with no entry text.
 */

const Boom = defineComponent({
  name: 'Boom',
  setup() {
    throw new Error('render exploded')
  },
  render: () => h('div'),
})

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/',
        name: 'journal',
        component: { render: () => h('div', 'ok') },
      },
    ],
  })
}

async function mountWith(child: unknown) {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  return mount(ErrorBoundary, {
    slots: { default: () => h(child as never) },
    global: { plugins: [router] },
  })
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
  vi.stubGlobal('fetch', fetchMock)
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ErrorBoundary', () => {
  it('renders the slot when nothing throws', async () => {
    const wrapper = await mountWith({ render: () => h('p', 'healthy') })
    expect(wrapper.text()).toContain('healthy')
    expect(wrapper.text()).not.toContain('stopped rendering')
    wrapper.unmount()
  })

  it('replaces a crashing view with a recoverable panel', async () => {
    const wrapper = await mountWith(Boom)
    expect(wrapper.text()).toContain('This view stopped rendering')
    expect(wrapper.text()).toContain('render exploded')
    expect(wrapper.text()).toContain('Reload')
    wrapper.unmount()
  })

  it('reports the failure to the backend without entry text', async () => {
    // Unique message: clientErrors dedupes identical reports for 5 s across the
    // module, and the panel test above already reported 'render exploded'.
    const ReportBoom = defineComponent({
      name: 'ReportBoom',
      setup() {
        throw new Error('report this one')
      },
      render: () => h('div'),
    })
    const wrapper = await mountWith(ReportBoom)
    const call = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes('/api/v1/system/client-errors'),
    )
    expect(call).toBeTruthy()
    const body = JSON.parse(String((call?.[1] as RequestInit).body))
    expect(body.message).toBe('report this one')
    expect(body.view).toBe('journal')
    expect(Object.keys(body).sort()).toEqual(
      [
        'app_version',
        'component',
        'message',
        'stack',
        'url',
        'view',
      ].sort(),
    )
    wrapper.unmount()
  })
})
