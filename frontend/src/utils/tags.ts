/**
 * Hashtag extraction for "tags live in the text".
 *
 * Tags are written inline as `#name` in the note/entry body. A `#` only starts a
 * tag when not preceded by a word/hyphen char (so `foo#bar` and markdown `# `
 * headings don't count). On save, the editor extracts the names and resolves
 * them to tag ids, creating any that don't exist yet.
 */
const HASHTAG_RE = /(?<![\w-])#([\w-]+)/g

/** Unique tag names found as `#tokens` in the body. */
export function extractHashtags(body: string): string[] {
  const names = new Set<string>()
  let m: RegExpExecArray | null
  HASHTAG_RE.lastIndex = 0
  while ((m = HASHTAG_RE.exec(body))) names.add(m[1])
  return [...names]
}
