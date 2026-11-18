/**
 * noteColors — the palette behind notebook/note colour labels.
 *
 * Stored values are the hex strings already accepted by `Note.color` /
 * `NoteFolder.color` (String(20)), not palette ids: an existing row keeps its
 * colour even if the palette is reordered, and exports carry a readable value.
 *
 * The eight 600-weight tones are chosen to stay distinguishable on both the
 * light and dark surfaces (≥ 3:1 against each), which the unit test pins.
 */

export interface NoteColor {
  /** Stable id for keys/aria, not persisted. */
  id: string
  label: string
  /** Persisted value. */
  value: string
}

export const NOTE_COLORS: readonly NoteColor[] = [
  { id: 'slate', label: 'Slate', value: '#64748b' },
  { id: 'rose', label: 'Rose', value: '#e11d48' },
  { id: 'amber', label: 'Amber', value: '#d97706' },
  { id: 'emerald', label: 'Emerald', value: '#059669' },
  { id: 'sky', label: 'Sky', value: '#0284c7' },
  { id: 'violet', label: 'Violet', value: '#7c3aed' },
  { id: 'lime', label: 'Lime', value: '#65a30d' },
  { id: 'fuchsia', label: 'Fuchsia', value: '#c026d3' },
]

function normalize(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase()
}

/** Palette entry for a stored value, or null (unset / unknown). */
export function noteColor(value: string | null | undefined): NoteColor | null {
  const v = normalize(value)
  if (!v) return null
  return NOTE_COLORS.find((c) => c.value.toLowerCase() === v) ?? null
}

/** CSS colour for a stored value; unknown values are ignored (no tint). */
export function noteColorValue(value: string | null | undefined): string | null {
  return noteColor(value)?.value ?? null
}

export function noteColorLabel(value: string | null | undefined): string | null {
  return noteColor(value)?.label ?? null
}

function channel(value: number): number {
  const c = value / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

/** WCAG relative luminance of a #rrggbb colour. */
export function relativeLuminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return 0
  const n = Number.parseInt(m[1], 16)
  return (
    0.2126 * channel((n >> 16) & 0xff) +
    0.7152 * channel((n >> 8) & 0xff) +
    0.0722 * channel(n & 0xff)
  )
}

/** WCAG contrast ratio (1–21) between two #rrggbb colours. */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a)
  const lb = relativeLuminance(b)
  const lighter = Math.max(la, lb)
  const darker = Math.min(la, lb)
  return (lighter + 0.05) / (darker + 0.05)
}
