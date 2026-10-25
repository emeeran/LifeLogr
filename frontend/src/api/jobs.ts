import { request, blobRequest, API_ORIGIN } from './client'

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

/** 202-style body from an `as_job=true` data operation. */
export interface JobStartResponse {
  job_id: string
  kind: string
}

export const jobsApi = {
  get(jobId: string): Promise<JobState> {
    return request(`/jobs/${jobId}`)
  },

  /** Start an export as a polled job. Takes one of the api/*Url() builders'
   *  full URLs; `as_job=true` is appended and the JSON body returned. */
  startExport(url: string): Promise<JobStartResponse> {
    const path = url.startsWith(API_ORIGIN) ? url.slice(API_ORIGIN.length) : url
    const sep = path.includes('?') ? '&' : '?'
    return request(`${path}${sep}as_job=true`)
  },

  /** Download a finished export job's file (server deletes it after). */
  result(jobId: string): Promise<Blob> {
    return blobRequest(`/jobs/${jobId}/result`)
  },
}
