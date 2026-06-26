/**
 * Settings utility helpers.
 *
 * - `providerLabel`: human-friendly names for backup providers (replaces
 *   ad-hoc `provider.replace('_', ' ')` which produced "google drive").
 * - `migrateLegacyKeys`: one-time, generic rename of every legacy
 *   `diarium-*` localStorage key to the `lifelogr-*` namespace, preserving
 *   values. Idempotent and safe to call on every startup.
 */

const PROVIDER_LABELS: Record<string, string> = {
  webdav: 'WebDAV',
  google_drive: 'Google Drive',
  onedrive: 'OneDrive',
  dropbox: 'Dropbox',
  nas: 'NAS',
  local_file: 'Local File',
}

export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

let migrated = false

/**
 * Rename every `diarium-*` localStorage key to `lifelogr-*`, copying the
 * stored value. Must run BEFORE any `useLocalStorage('diarium-…')` store
 * binds (i.e. at the very top of main.ts, before the app mounts).
 * Idempotent: a second run finds no `diarium-*` keys and does nothing.
 */
export function migrateLegacyKeys(): void {
  if (migrated) return
  migrated = true
  const toMigrate: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key && key.startsWith('diarium-')) toMigrate.push(key)
  }
  for (const oldKey of toMigrate) {
    const newKey = 'lifelogr-' + oldKey.slice('diarium-'.length)
    if (!(newKey in localStorage)) {
      localStorage.setItem(newKey, localStorage.getItem(oldKey)!)
    }
    localStorage.removeItem(oldKey)
  }
}
