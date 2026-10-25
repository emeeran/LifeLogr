import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * ExportPanel mount smoke test — every format row renders with a carries
 * label, the portable-vs-full-instance explainer is present, and the archive
 * row drives a polled export job into saveFile.
 */

const startExport = vi.fn(async (_url: string) => ({
  job_id: 'job-9',
  kind: 'export-archive',
}))
const result = vi.fn(async (_id: string) => new Blob(['PKzip'], { type: 'application/zip' }))
const saveFile = vi.fn(async (_opts?: unknown) => true)

vi.mock('../../../api/jobs', () => ({
  jobsApi: {
    startExport: (url: string) => startExport(url),
    result: (id: string) => result(id),
    get: vi.fn(async () => ({
      id: 'job-9',
      kind: 'export-archive',
      status: 'done',
      phase: '',
      done: 1,
      total: 1,
      percent: null,
      detail: null,
      error: null,
      created_at: 0,
      finished_at: 1,
    })),
  },
}))
const urlBuilders = {
  exportArchiveUrl: vi.fn(() => '/entries/export/archive'),
  exportMarkdownUrl: vi.fn(() => '/entries/export/markdown'),
  exportHtmlZipUrl: vi.fn(() => '/entries/export/html-zip'),
  exportJsonUrl: vi.fn(() => '/entries/export/json'),
  exportDaylioCsvUrl: vi.fn(() => '/entries/export/daylio-csv'),
}
vi.mock('../../../api/entries', () => ({ entriesApi: urlBuilders }))
vi.mock('../../../api/export', () => ({
  exportHtml: vi.fn(async () => '<html></html>'),
  getExportPdfUrl: vi.fn(() => '/entries/export/pdf'),
  exportDiarium: vi.fn(async () => '[]'),
  getExportDiariumDbUrl: vi.fn(() => '/entries/export/diarium-db'),
}))
vi.mock('../../../api/notes', () => ({
  notesApi: {
    exportMarkdownUrl: () => '/notes/export/markdown',
    exportJsonUrl: () => '/notes/export/json',
    exportHtmlUrl: () => '/notes/export/html',
  },
}))
vi.mock('../../../utils/fileDialog', () => ({
  saveFile: (...args: unknown[]) => saveFile(...(args as [])),
  pickFile: vi.fn(),
}))

async function mountPanel() {
  const { default: ExportPanel } = await import('./ExportPanel.vue')
  const wrapper = mount(ExportPanel)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  startExport.mockClear()
  result.mockClear()
  saveFile.mockClear()
})

describe('ExportPanel mount', () => {
  it('renders every format row with carries labels and the explainer', async () => {
    const wrapper = await mountPanel()
    const text = wrapper.text()
    // Entries formats
    expect(text).toContain('Archive ZIP')
    expect(text).toContain('Diarium .diary')
    expect(text).toContain('Markdown ZIP')
    expect(text).toContain('HTML archive')
    expect(text).toContain('Diarium CSV (Daylio)')
    // Notes formats live in the same panel
    expect(text).toContain('Notes')
    // Carry labels + explainer
    expect(text).toContain('entries · media · tags')
    expect(text).toContain('Portable export')
    expect(text).toContain('full-instance backup')
    wrapper.unmount()
  })

  it('exports the archive via a polled job and saves the result', async () => {
    const wrapper = await mountPanel()
    const archiveButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('Export'))
    await archiveButton!.trigger('click')
    await flushPromises()

    // as_job=true is appended by startExport; the URL comes from the builder.
    expect(startExport).toHaveBeenCalledWith('/entries/export/archive')
    expect(saveFile).toHaveBeenCalledTimes(1)
    const opts = saveFile.mock.calls[0]?.[0] as {
      defaultName?: string
    }
    expect(opts.defaultName).toBe('lifelogr-archive.zip')
    wrapper.unmount()
  })
})
