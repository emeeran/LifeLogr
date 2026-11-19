import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  isTauri: true,
  open: vi.fn(),
  invoke: vi.fn(),
}))

vi.mock('../api/client', () => ({
  get isTauri() {
    return mocks.isTauri
  },
}))
vi.mock('@tauri-apps/plugin-dialog', () => ({ open: mocks.open }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }))

import { pickAndUploadJson, pickPath } from './fileDialog'

beforeEach(() => {
  mocks.isTauri = true
  mocks.open.mockReset()
  mocks.invoke.mockReset()
})

describe('pickPath', () => {
  it('returns the picked path in Tauri', async () => {
    mocks.open.mockResolvedValue('/run/media/em/diary/Diarium.diary')
    await expect(pickPath({ accept: '.diary,.json' })).resolves.toBe(
      '/run/media/em/diary/Diarium.diary',
    )
    expect(mocks.open).toHaveBeenCalledWith({
      multiple: false,
      filters: [
        { name: 'Files', extensions: ['diary', 'json'] },
      ],
    })
  })

  it('returns null on cancel', async () => {
    mocks.open.mockResolvedValue(null)
    await expect(pickPath()).resolves.toBeNull()
  })

  it('returns null in browser without opening a dialog', async () => {
    mocks.isTauri = false
    await expect(pickPath()).resolves.toBeNull()
    expect(mocks.open).not.toHaveBeenCalled()
  })
})

describe('pickAndUploadJson', () => {
  it('streams the picked file via upload_file_as and parses the response', async () => {
    mocks.open.mockResolvedValue('/tmp/backup.tar.gz')
    mocks.invoke.mockResolvedValue('{"job_id":"j1"}')
    await expect(
      pickAndUploadJson<{ job_id: string }>('/backup/import?as_job=true', '.tar.gz,.tgz'),
    ).resolves.toEqual({ job_id: 'j1' })
    // Tauri v2 renames snake_case args to camelCase at the boundary.
    expect(mocks.invoke).toHaveBeenCalledWith('upload_file_as', {
      filePath: '/tmp/backup.tar.gz',
      pathQuery: '/backup/import?as_job=true',
      fieldName: 'file',
    })
  })

  it('returns null when the user cancels without invoking the backend', async () => {
    mocks.open.mockResolvedValue(null)
    await expect(pickAndUploadJson('/backup/verify', '.tar.gz')).resolves.toBeNull()
    expect(mocks.invoke).not.toHaveBeenCalled()
  })
})
