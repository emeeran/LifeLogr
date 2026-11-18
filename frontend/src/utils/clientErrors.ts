/**
 * clientErrors — report renderer failures to the backend log.
 *
 * The desktop UI runs in a devtools-less webview, so a component crash or an
 * unhandled rejection is otherwise invisible. Reports are text-only by design:
 * message, stack, component, URL (query/fragment stripped) and view name. Entry
 * and note content is never included.
 *
 * Reporting must never throw or recurse: a failure to report is swallowed, and
 * identical messages are deduplicated locally before they reach the backend's
 * own rate limiter.
 */
import { API_ORIGIN } from '../api/client'
import { APP_VERSION } from '../version'

export interface ClientErrorReport {
  message: string
  stack?: string
  component?: string
  url?: string
  view?: string
}

const DEDUPE_MS = 5000
let lastKey = ''
let lastAt = 0

function truncate(value: string | undefined, max: number): string | undefined {
  if (!value) return undefined
  return value.length > max ? value.slice(0, max) : value
}

export function reportClientError(report: ClientErrorReport): void {
  try {
    const key = `${report.message}\u0000${report.component ?? ''}`
    const now = Date.now()
    if (key === lastKey && now - lastAt < DEDUPE_MS) return
    lastKey = key
    lastAt = now

    const body = JSON.stringify({
      message: truncate(report.message, 500) ?? 'Unknown error',
      stack: truncate(report.stack, 4000),
      component: truncate(report.component, 120),
      url: truncate(report.url, 300),
      view: truncate(report.view, 40),
      app_version: APP_VERSION,
    })
    void fetch(`${API_ORIGIN}/api/v1/system/client-errors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {
      /* reporting is best-effort; never surface its failure */
    })
  } catch {
    /* never let the reporter throw into the error path */
  }
}
