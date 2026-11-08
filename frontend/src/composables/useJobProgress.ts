import { computed, onUnmounted, ref, watch as watchRef, shallowRef } from 'vue'
import { ApiError } from '../api/client'
import { jobsApi, type JobState } from '../api/jobs'

const POLL_MS = 1000

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
  }

  async function poll(jobId: string) {
    if (disposed || jobId !== currentJobId) return
    try {
      const state = await jobsApi.get(jobId)
      if (jobId !== currentJobId) return // superseded mid-flight
      job.value = state
      error.value = null
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
      // mid-restart (e.g. right after a restore). Retry within the window.
      error.value = e instanceof Error ? e.message : 'Failed to fetch progress'
      timer = setTimeout(() => poll(jobId), POLL_MS)
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
