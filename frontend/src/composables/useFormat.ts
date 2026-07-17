/**
 * Format an ISO date string (YYYY-MM-DD) as a locale string.
 * Appends T00:00:00 to avoid UTC offset issues.
 */
export function formatEntryDate(iso: string, options?: Intl.DateTimeFormatOptions): string {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('en-US', options)
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
