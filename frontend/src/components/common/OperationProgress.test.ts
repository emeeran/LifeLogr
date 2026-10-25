import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import OperationProgress from './OperationProgress.vue'
import type { JobState } from '../../api/jobs'

/**
 * Progress bar for data operations: determinate when the backend reports a
 * total, indeterminate (pulsing) until then, distinct failed/done states.
 */

function makeJob(overrides: Partial<JobState> = {}): JobState {
  return {
    id: 'job-1',
    kind: 'backup',
    status: 'running',
    phase: 'media',
    done: 3,
    total: 10,
    percent: 30,
    detail: null,
    error: null,
    created_at: 0,
    finished_at: null,
    ...overrides,
  }
}

describe('OperationProgress', () => {
  it('renders nothing without a job', () => {
    const wrapper = mount(OperationProgress, { props: { job: null } })
    expect(wrapper.find('[data-testid="operation-progress"]').exists()).toBe(
      false,
    )
  })

  it('shows phase, count, and a determinate bar when total is known', () => {
    const wrapper = mount(OperationProgress, {
      props: { job: makeJob({ detail: 'copying' }), label: 'Backup' },
    })
    expect(wrapper.text()).toContain('Backup: Media — copying')
    expect(wrapper.text()).toContain('3 / 10')
    const bar = wrapper.find('[data-testid="operation-progress"] .h-full')
    expect(bar.attributes('style')).toContain('width: 30%')
  })

  it('runs indeterminate (no width, pulsing) when total is unknown', () => {
    const wrapper = mount(OperationProgress, {
      props: { job: makeJob({ total: null, percent: null }) },
    })
    expect(wrapper.text()).not.toContain('/')
    const bar = wrapper.find('[data-testid="operation-progress"] .h-full')
    expect(bar.attributes('style')).toBeUndefined()
    expect(bar.classes()).toContain('animate-pulse')
  })

  it('paints failed red with the error text at full width', () => {
    const wrapper = mount(OperationProgress, {
      props: { job: makeJob({ status: 'failed', error: 'disk full' }) },
    })
    expect(wrapper.text()).toContain('disk full')
    const bar = wrapper.find('[data-testid="operation-progress"] .h-full')
    expect(bar.classes()).toContain('bg-danger')
  })

  it('snaps the bar to full accent on done', () => {
    const wrapper = mount(OperationProgress, {
      props: { job: makeJob({ status: 'done' }) },
    })
    const bar = wrapper.find('[data-testid="operation-progress"] .h-full')
    expect(bar.classes()).toContain('bg-accent')
    expect(wrapper.text()).not.toContain('/') // count hidden when finished
  })
})
