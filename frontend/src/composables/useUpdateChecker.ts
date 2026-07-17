/**
 * useUpdateChecker — checks GitHub Releases for a newer LifeLogr version.
 *
 * Offline-first philosophy: the app is fully usable without a network, so a
 * failed update check is the *normal* case and must never block or alarm the
 * user. The composable exposes reactive state that the UI reads; all network
 * errors collapse to a single `offline` status.
 *
 * Source of truth for the latest version is the GitHub Releases API for the
 * configured repo. Version comparison is semver-style (major.minor.patch),
 * tolerating a leading `v`.
 *
 * Auto-check: an opt-in weekly background check is available. The last check
 * timestamp and the last-known installed version are persisted to localStorage
 * so the first-run "What's New" dialog can show what changed since the user's
 * previous version.
 */
import { ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { APP_VERSION } from '../version'

/** Canonical GitHub repo (no trailing slash). */
export const REPO_URL = 'https://github.com/emeeran/LifeLogr'
const RELEASES_API = `https://api.github.com/repos/emeeran/LifeLogr/releases/latest`

export type UpdateStatus =
  | { kind: 'idle' }
  | { kind: 'checking' }
  | { kind: 'up-to-date'; latest: string }
  | { kind: 'available'; latest: string; url: string; publishedAt: string | null; notes: string | null }
  | { kind: 'offline'; message: string }

/** Parse a version or tag into a tuple of numbers, tolerating a leading "v". */
function parseVersion(v: string): [number, number, number] {
  const m = v.trim().replace(/^v/i, '').match(/^(\d+)\.(\d+)\.(\d+)/)
  if (!m) return [0, 0, 0]
  return [Number(m[1]), Number(m[2]), Number(m[3])]
}

/** Returns true if `latest` is strictly newer than `current` (semver). */
function isNewer(current: string, latest: string): boolean {
  const [a1, a2, a3] = parseVersion(current)
  const [b1, b2, b3] = parseVersion(latest)
  if (b1 !== a1) return b1 > a1
  if (b2 !== a2) return b2 > a2
  return b3 > a3
}

interface GitHubRelease {
  tag_name: string
  html_url: string
  published_at: string
  body: string | null
}

export function useUpdateChecker() {
  const status = ref<UpdateStatus>({ kind: 'idle' })
  const checkedAt = ref<Date | null>(null)

  // ── Persisted preferences (shared across all callers via localStorage) ──
  /** Opt-in weekly background update check. Off by default (privacy-first). */
  const autoCheckEnabled = useLocalStorage<boolean>('lifelogr-update-autocheck', false)
  /** Epoch-ms of the last background check (throttle to once per week). */
  const lastCheckedAt = useLocalStorage<number>('lifelogr-update-last-checked', 0)
  /** The installed version the user last saw the "What's New" dialog for. */
  const lastSeenVersion = useLocalStorage<string>('lifelogr-update-last-seen', '')

  /** True when the installed version is newer than what the user last acknowledged. */
  const hasUnseenVersion = (() => {
    const last = lastSeenVersion.value
    return !last || isNewer(last, APP_VERSION) || APP_VERSION !== last
  })()

  /** Mark the current version as seen (suppresses the first-run dialog). */
  function markCurrentVersionSeen(): void {
    lastSeenVersion.value = APP_VERSION
  }

  async function check(): Promise<void> {
    status.value = { kind: 'checking' }
    try {
      const res = await fetch(RELEASES_API, {
        headers: { Accept: 'application/vnd.github+json' },
        // Don't cache — we want the freshest release tag.
        cache: 'no-store',
      })
      if (!res.ok) {
        throw new Error(`GitHub API returned ${res.status}`)
      }
      const data = (await res.json()) as GitHubRelease
      const latest = data.tag_name
      checkedAt.value = new Date()
      if (isNewer(APP_VERSION, latest)) {
        status.value = {
          kind: 'available',
          latest,
          url: data.html_url,
          publishedAt: data.published_at ?? null,
          notes: data.body ?? null,
        }
      } else {
        status.value = { kind: 'up-to-date', latest }
      }
    } catch (e) {
      status.value = {
        kind: 'offline',
        message: e instanceof Error ? e.message : 'Network unavailable',
      }
    }
  }

  function reset(): void {
    status.value = { kind: 'idle' }
  }

  /** Minimum gap between automatic background checks (7 days, in ms). */
  const AUTO_CHECK_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000

  /**
   * Run a background check if the user opted in and a week has passed.
   * Safe to call on every app startup. Returns true if a check was performed.
   * Never throws — offline-first.
   */
  async function maybeAutoCheck(): Promise<boolean> {
    if (!autoCheckEnabled.value) return false
    const elapsed = Date.now() - (lastCheckedAt.value || 0)
    if (elapsed < AUTO_CHECK_INTERVAL_MS) return false
    lastCheckedAt.value = Date.now()
    try {
      await check()
    } catch {
      /* swallow — background check must never interrupt the user */
    }
    return true
  }

  return {
    status, checkedAt, check, reset,
    autoCheckEnabled, lastCheckedAt, lastSeenVersion,
    hasUnseenVersion, markCurrentVersionSeen, maybeAutoCheck,
  }
}
