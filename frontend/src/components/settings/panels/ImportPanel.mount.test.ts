import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * ImportPanel mount smoke test — entries + notes import sections render, the
 * entries menu drives the file picker into a polled import job, and the job's
 * terminal state lands as a toast.
 */

const importFileJob = vi.fn(async (_file: File) => ({
  job_id: 'job-1',
  kind: 'import',
}))
vi.mock('../../../api/entries', () => ({
  entriesApi: {
    importFileJob: (file: File) => importFileJob(file),
  },
}))
vi.mock('../../../api/notes', () => ({
  notesApi: {
    importFileJob: vi.fn(async () => ({ job_id: 'job-2', kind: 'import-notes' })),
  },
}))
vi.mock('../../../utils/fileDialog', () => ({
  pickFile: vi.fn(async () => new File(['x'], 'import.diary')),
  saveFile: vi.fn(async () => true),
}))
vi.mock('../../../api/jobs', () => ({
  jobsApi: {
    get: vi.fn(async () => ({
      id: 'job-1',
      kind: 'import',
      status: 'done',
      phase: '',
      done: 3,
      total: 3,
      percent: null,
      detail: 'Imported 3 entries',
      error: null,
      created_at: 0,
      finished_at: 1,
    })),
    startExport: vi.fn(),
    result: vi.fn(),
  },
}))
vi.mock('../../../stores/entries', () => ({
  useEntriesStore: () => ({ refreshAll: vi.fn() }),
}))

async function mountPanel() {
  const { default: ImportPanel } = await import('./ImportPanel.vue')
  const wrapper = mount(ImportPanel)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  importFileJob.mockClear()
})

describe('ImportPanel mount', () => {
  it('renders entries and notes import sections', async () => {
    const wrapper = await mountPanel()
    const text = wrapper.text()
    expect(text).toContain('Import entries')
    expect(text).toContain('Import notes')
    expect(text).toContain('Duplicate entries (same date + body) are skipped')
    wrapper.unmount()
  })

  it('runs a picked file through the import job and toasts the result', async () => {
    const wrapper = await mountPanel()
    // Open the entries menu and pick the Diarium format.
    await wrapper.findAll('button').find((b) => b.text().includes('Import…'))!.trigger('click')
    await wrapper.find('button.import-item').trigger('click')
    await flushPromises()

    expect(importFileJob).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Imported 3 entries')
    wrapper.unmount()
  })
})
