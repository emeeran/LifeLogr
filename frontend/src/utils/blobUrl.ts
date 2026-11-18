/**
 * Tracked blob object URLs.
 *
 * `URL.createObjectURL` pins the underlying blob in memory until
 * `URL.revokeObjectURL` runs, and a forgotten revoke is invisible — no error,
 * just memory that never frees (the same class of slow leak that OOMed the
 * WebKit renderer). Every object URL the app creates goes through here:
 *
 *  • `createTrackedObjectUrl` records the URL in a live-set.
 *  • `revokeTrackedObjectUrl` revokes it and drops the record; it is
 *    idempotent, tolerant of empty/null input, and a no-op for URLs it did
 *    not create — so unmount/stop paths can call it unconditionally.
 *
 * `liveTrackedObjectUrlCount` exposes the outstanding balance for tests and
 * diagnostics.
 */
const live = new Set<string>()

export function createTrackedObjectUrl(blob: Blob): string {
  const url = URL.createObjectURL(blob)
  live.add(url)
  return url
}

export function revokeTrackedObjectUrl(url: string | null | undefined): void {
  if (!url) return
  // Only revoke URLs we created: `URL.revokeObjectURL` on a foreign string is
  // silently ignored by the browser, but dropping it here keeps the set honest.
  if (!live.delete(url)) return
  URL.revokeObjectURL(url)
}

/** Object URLs created here and not yet revoked (tests / diagnostics). */
export function liveTrackedObjectUrlCount(): number {
  return live.size
}
