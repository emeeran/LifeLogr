import { request } from './client'

/** State of a background data operation (backup/restore/import/export),
 *  mirrored from the backend's in-memory job registry. */
export interface JobState {
  id: string
  kind: string
  status: 'running' | 'done' | 'failed'
  phase: string
  done: number
  total: number | null
  percent: number | null
  detail: string | null
  error: string | null
  created_at: number
  finished_at: number | null
}

export const jobsApi = {
  get(jobId: string): Promise<JobState> {
    return request(`/jobs/${jobId}`)
  },
}
