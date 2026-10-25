import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * BackupRestorePanel mount smoke test — the three backup sections render, a
 * single "Run now" exists, and on-mount config/snapshot fetches fire.
 */

vi.mock('../../../api/client', () => ({
  isTauri: false,
  request: vi.fn(async () => ({
    running: false,
    backup_scheduled: false,
    next_run: null,
  })),
  blobRequest: vi.fn(),
}))
const backupApiMocks = {
  exportLocal: vi.fn(() => '/backup/export'),
  importLocal: vi.fn(),
  runBackupJob: vi.fn(),
  restoreJob: vi.fn(),
  runNowLocalJob: vi.fn(),
  createConfig: vi.fn(),
  testConnection: vi.fn(),
  deleteSnapshot: vi.fn(),
  scheduleBackup: vi.fn(),
  getSchedule: vi.fn(async () => ({ configured: false })),
  getGoogleDriveAuthUrl: vi.fn(),
  getBoxAuthUrl: vi.fn(),
}
vi.mock('../../../api/backup', () => ({ backupApi: backupApiMocks }))
vi.mock('../../../stores/backup', () => ({
  useBackupStore: () => ({
    configs: [],
    snapshots: [],
    fetchConfigs: vi.fn(),
    fetchSnapshots: vi.fn(),
    deleteConfig: vi.fn(),
  }),
}))
vi.mock('../../../stores/entries', () => ({
  useEntriesStore: () => ({ refreshAll: vi.fn() }),
}))
vi.mock('../../../utils/fileDialog', () => ({
  saveFile: vi.fn(async () => true),
  pickFile: vi.fn(),
  pickFolder: vi.fn(),
}))

async function mountPanel() {
  const { default: BackupRestorePanel } = await import(
    './BackupRestorePanel.vue'
  )
  const wrapper = mount(BackupRestorePanel)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  for (const m of Object.values(backupApiMocks)) m.mockClear()
  localStorage.clear()
})

describe('BackupRestorePanel mount', ()  => {
  it('renders local, scheduled, and cloud backup sections', async () => {
    const wrapper = await mountPanel()
    const text = wrapper.text()
    expect(text).toContain('Local Backup')
    expect(text).toContain('Scheduled Backup')
    expect(text).toContain('Cloud Backup')
    expect(text).toContain('No cloud backups configured.')
    wrapper.unmount()
  })

  it('has exactly one "Run now" button', async () => {
    // The button lives inside the enabled-schedule branch.
    localStorage.setItem('lifelogr-auto-backup-enabled', 'true')
    const wrapper = await mountPanel()
    expect(
      wrapper.findAll('button').filter((b) => b.text().includes('Run now')),
    ).toHaveLength(1)
    wrapper.unmount()
  })

  it('loads the persisted schedule on mount', async () => {
    await mountPanel()
    expect(backupApiMocks.getSchedule).toHaveBeenCalledTimes(1)
  })
})
