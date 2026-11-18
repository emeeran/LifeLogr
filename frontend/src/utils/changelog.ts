/**
 * Extracts a version's section from the raw CHANGELOG.md text.
 *
 * Shared by the What's New dialog and the About tab. The What's New dialog
 * must only ever surface a *released* version's notes — showing the
 * `[Unreleased]` section leaks in-progress dev notes to end users.
 */

/** True if a `## [...]` heading is the changelog's Unreleased bucket. */
export function isUnreleasedHeading(heading: string): boolean {
  return /\[\s*[Uu]nreleased\s*\]/.test(heading)
}

/**
 * Return the latest *released* version's section (heading line included),
 * or null when the changelog has no released section (fresh project).
 */
export function latestReleasedSection(raw: string): string | null {
  const lines = raw.split('\n')
  const headingIdx = lines.findIndex(
    (l) => l.startsWith('## [') && !isUnreleasedHeading(l),
  )
  if (headingIdx < 0) return null
  const next = lines.findIndex(
    (l, i) => i > headingIdx && l.startsWith('## ['),
  )
  return lines.slice(headingIdx, next < 0 ? lines.length : next).join('\n')
}
