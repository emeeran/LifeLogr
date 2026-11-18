import { describe, expect, it } from 'vitest'
import { isUnreleasedHeading, latestReleasedSection } from './changelog'

const CHANGELOG = `# Changelog

All notable changes.

## [Unreleased]

### Fixed
- in-progress dev note

## [1.2.0] — 2026-11-01

### Added
- shipped feature

## [1.1.0] — 2026-10-01

### Fixed
- older fix
`

describe('isUnreleasedHeading', () => {
  it('matches the Unreleased bucket regardless of case/spacing', () => {
    expect(isUnreleasedHeading('## [Unreleased]')).toBe(true)
    expect(isUnreleasedHeading('## [ unreleased ]')).toBe(true)
  })

  it('does not match released headings', () => {
    expect(isUnreleasedHeading('## [1.2.0] — 2026-11-01')).toBe(false)
  })
})

describe('latestReleasedSection', () => {
  it('skips Unreleased and returns the newest released section', () => {
    const section = latestReleasedSection(CHANGELOG)
    expect(section).toContain('## [1.2.0]')
    expect(section).toContain('shipped feature')
    expect(section).not.toContain('in-progress dev note')
    expect(section).not.toContain('older fix')
  })

  it('returns the last section when it is the final one', () => {
    const raw = '## [Unreleased]\n\n- wip\n\n## [0.9.0]\n\n- last release'
    expect(latestReleasedSection(raw)).toContain('0.9.0')
  })

  it('returns null when only Unreleased exists', () => {
    expect(latestReleasedSection('## [Unreleased]\n\n- wip')).toBeNull()
    expect(latestReleasedSection('')).toBeNull()
  })
})
