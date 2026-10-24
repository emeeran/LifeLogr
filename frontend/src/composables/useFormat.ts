/**
 * Format an ISO date string (YYYY-MM-DD) as a locale string.
 * Appends T00:00:00 to avoid UTC offset issues.
 */
export function formatEntryDate(
  iso: string,
  options?: Intl.DateTimeFormatOptions,
): string {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('en-US', options)
}

/**
 * Journal date display standard: dd-mm-yyyy. Storage and the API stay ISO
 * (YYYY-MM-DD); only what the user sees is converted.
 */

/** Strict ISO → dd-mm-yyyy ("25-08-2026", optionally "Mon 25-08-2026").
 *  Returns the input unchanged when it isn't a real calendar date, so legacy
 *  rows never render as garbage. */
export function formatDDMMYYYY(
  iso: string,
  opts?: { weekday?: 'short' | 'long' },
): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim())
  if (!m) return iso
  const [, y, mo, d] = m
  const date = new Date(Number(y), Number(mo) - 1, Number(d))
  if (
    date.getFullYear() !== Number(y) ||
    date.getMonth() !== Number(mo) - 1 ||
    date.getDate() !== Number(d)
  ) {
    return iso
  }
  const weekdays =
    opts?.weekday === 'long'
      ? [
          'Sunday',
          'Monday',
          'Tuesday',
          'Wednesday',
          'Thursday',
          'Friday',
          'Saturday',
        ]
      : ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const prefix = opts?.weekday ? `${weekdays[date.getDay()]} ` : ''
  return `${prefix}${d}-${mo}-${y}`
}

/** Strict dd-mm-yyyy (any non-digit separators, or bare digits) → ISO.
 *  Validates as a real calendar date (rejects 31-02, 29-02 off leap years).
 *  Returns null when not a complete, valid date. */
export function parseDDMMYYYY(s: string): string | null {
  const digits = s.replace(/\D/g, '')
  if (digits.length !== 8) return null
  const d = Number(digits.slice(0, 2))
  const mo = Number(digits.slice(2, 4))
  const y = Number(digits.slice(4, 8))
  if (mo < 1 || mo > 12) return null
  const date = new Date(y, mo - 1, d)
  if (date.getMonth() !== mo - 1 || date.getDate() !== d) return null
  return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

/** ISO → the masked dd-mm-yyyy text shown in the editor's date field. */
export function isoToDDMMYYYYInput(iso: string): string {
  const parsed = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim())
  return parsed ? `${parsed[3]}-${parsed[2]}-${parsed[1]}` : iso
}

/** Apply the dd-mm-yyyy mask to raw typed text: digits only, max 8, dashes
 *  after the day (2) and month (4). Used by the editor's date input. */
export function maskDDMMYYYY(text: string): string {
  const digits = text.replace(/\D/g, '').slice(0, 8)
  let masked = ''
  if (digits.length > 0) masked = digits.slice(0, 2)
  if (digits.length > 2) masked += '-' + digits.slice(2, 4)
  if (digits.length > 4) masked += '-' + digits.slice(4, 8)
  return masked
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
