import { computed, onUnmounted, ref, shallowRef } from 'vue'
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

  onUnmounted(() => {
    disposed = true
    stop()
  })

  return { job, running, failed, done, percent, phase, error, watch, stop }
}
