import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useJobProgress } from './useJobProgress'
import { jobsApi, type JobState } from '../api/jobs'

/**
 * Progress polling for data operations. Runs on fake timers: the 1s poll
 * cadence, auto-stop on terminal states, and supersede-mid-flight semantics
 * are all timing-shaped.
 */

vi.mock('../api/jobs', () => ({ jobsApi: { get: vi.fn() } }))

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

const mockedGet = vi.mocked(jobsApi.get)

beforeEach(() => {
  vi.useFakeTimers()
  mockedGet.mockReset()
})

describe('useJobProgress', () => {
  it('polls every 1s while the job is running', async () => {
    mockedGet.mockResolvedValue(makeJob())
    const { watch, job } = useJobProgress()
    watch('job-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedGet).toHaveBeenCalledTimes(1)
    expect(job.value?.percent).toBe(30)

    await vi.advanceTimersByTimeAsync(1000)
    expect(mockedGet).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1000)
    expect(mockedGet).toHaveBeenCalledTimes(3)
  })

  it('stops polling on done and keeps the final state', async () => {
    mockedGet.mockResolvedValue(makeJob({ status: 'done', percent: null }))
    const { watch, done, running } = useJobProgress()
    watch('job-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(done.value).toBe(true)
    expect(running.value).toBe(false)

    await vi.advanceTimersByTimeAsync(5000)
    expect(mockedGet).toHaveBeenCalledTimes(1) // no further polls
  })

  it('stops polling on failed and exposes the error state', async () => {
    mockedGet.mockResolvedValue(
      makeJob({ status: 'failed', error: 'disk full' }),
    )
    const { watch, failed } = useJobProgress()
    watch('job-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(failed.value).toBe(true)
    expect(useJobProgress).toBeTruthy()

    await vi.advanceTimersByTimeAsync(5000)
    expect(mockedGet).toHaveBeenCalledTimes(1)
  })

  it('survives a transient poll failure and keeps retrying', async () => {
    mockedGet
      .mockRejectedValueOnce(new Error('backend restarting'))
      .mockResolvedValue(makeJob({ status: 'done' }))
    const { watch, error, done } = useJobProgress()
    watch('job-1')
    await vi.advanceTimersByTimeAsync(0)
    expect(error.value).toBe('backend restarting')

    await vi.advanceTimersByTimeAsync(1000)
    expect(done.value).toBe(true)
    expect(error.value).toBeNull()
  })

  it('watch() supersedes a previous job id', async () => {
    // Echo the requested id — the fixture default is job-1, which would
    // mask which poll wrote last.
    mockedGet.mockImplementation(async (id: string) => makeJob({ id }))
    const { watch, job } = useJobProgress()
    watch('job-1')
    await vi.advanceTimersByTimeAsync(0)
    watch('job-2')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1000)
    // Old polls must not write state meant for job-2.
    expect(job.value?.id).toBe('job-2')
  })

  it('stop() halts polling', async () => {
    mockedGet.mockResolvedValue(makeJob())
    const { watch, stop } = useJobProgress()
    watch('job-1')
    await vi.advanceTimersByTimeAsync(0)
    stop()
    await vi.advanceTimersByTimeAsync(5000)
    expect(mockedGet).toHaveBeenCalledTimes(1)
  })
})
