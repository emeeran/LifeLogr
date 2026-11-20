import { computed, onUnmounted, ref, watch as watchRef, shallowRef } from 'vue'
import { ApiError } from '../api/client'
import { jobsApi, type JobState } from '../api/jobs'
import { errorMessage } from '../utils/errorMessage'

const POLL_MS = 1000
/** Failed polls double their delay up to this cap so a down backend isn't
 *  hammered at 1 Hz for the whole job window. */
const MAX_POLL_MS = 15_000

/**
 * Poll a backend job until it finishes. Exposes the latest `JobState` plus
 * derived flags; `watch(jobId)` starts polling, `stop()` cancels. Polling
 * stops automatically on `done`/`failed` (final state stays available).
 */
export function useJobProgress() {
  const job = shallowRef<JobState | null>(null)
  const error = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | null = null
  let currentJobId: string | null = null
  let disposed = false
  /** Delay for the next poll after a failure; doubles per consecutive miss. */
  let failureDelayMs = POLL_MS

  const running = computed(() => job.value?.status === 'running')
  const failed = computed(() => job.value?.status === 'failed')
  const done = computed(() => job.value?.status === 'done')
  const percent = computed(() => job.value?.percent ?? null)
  const phase = computed(() => job.value?.phase ?? '')

  function stop() {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    currentJobId = null
    // A fresh watch (or terminal state) starts the cadence over.
    failureDelayMs = POLL_MS
  }

  async function poll(jobId: string) {
    if (disposed || jobId !== currentJobId) return
    try {
      const state = await jobsApi.get(jobId)
      if (jobId !== currentJobId) return // superseded mid-flight
      job.value = state
      error.value = null
      failureDelayMs = POLL_MS // healthy poll — the cadence resets
      if (state.status === 'running') {
        timer = setTimeout(() => poll(jobId), POLL_MS)
      } else {
        stop()
      }
    } catch (e: unknown) {
      // A 404 is terminal: the job was evicted (jobs expire a few minutes
      // after finishing) or the backend lost its job registry (restart).
      // Retrying forever would spin at 1 Hz on a state that can never
      // succeed and leave run()'s promise hanging.
      if (e instanceof ApiError && e.status === 404) {
        error.value = 'Job no longer exists (expired or backend restarted)'
        job.value = {
          id: jobId,
          kind: '',
          status: 'failed',
          phase: '',
          done: 0,
          total: null,
          percent: null,
          detail: null,
          error: error.value,
          created_at: 0,
          finished_at: Date.now() / 1000,
        }
        stop()
        return
      }
      // A single failed poll shouldn't kill the watch — the backend may be
      // mid-restart (e.g. right after a restore). Retry with exponential
      // backoff (1s → 15s cap) so a down backend isn't polled at 1 Hz.
      error.value = errorMessage(e) || 'Failed to fetch progress'
      timer = setTimeout(() => poll(jobId), failureDelayMs)
      failureDelayMs = Math.min(failureDelayMs * 2, MAX_POLL_MS)
    }
  }

  function watch(jobId: string) {
    stop()
    currentJobId = jobId
    job.value = null
    error.value = null
    void poll(jobId)
  }

  /** `watch` + wait for the terminal state; resolves with the final job
   *  (or null if superseded/stopped). Convenience for async handlers. */
  function run(jobId: string): Promise<JobState | null> {
    return new Promise((resolve) => {
      const stopWatcher = watchRef(job, (j) => {
        if (!j || j.status === 'running') return
        stopWatcher()
        resolve(j)
      })
      watch(jobId)
    })
  }

  onUnmounted(() => {
    disposed = true
    stop()
  })

  return { job, running, failed, done, percent, phase, error, watch, run, stop }
}
