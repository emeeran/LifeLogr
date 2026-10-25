/**
 * Text-measurement helpers shared by every word-count surface (editor stats
 * bar, daily goal, stats dashboard) so one definition of "word" applies
 * everywhere. Mirrors the backend's `len(text.split())` — whitespace-run
 * splitting on trimmed text — so both sides agree on counts.
 */

export function countWords(text: string | null | undefined): number {
  const trimmed = (text ?? '').trim()
  return trimmed ? trimmed.split(/\s+/).length : 0
}
