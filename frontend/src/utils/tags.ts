/**
 * Hashtag extraction + name→id resolution for "tags live in the text".
 *
 * Tags are written inline as `#name` in the note/entry body. A `#` only starts a
 * tag when not preceded by a word/hyphen char (so `foo#bar` and markdown `# `
 * headings don't count). On save, the editor extracts the names and resolves
 * them to tag ids, creating any that don't exist yet.
 */
import { tagsApi } from '../api/tags'
import { useTagsStore } from '../stores/tags'

const HASHTAG_RE = /(?<![\w-])#([\w-]+)/g

/** Unique tag names found as `#tokens` in the body. */
export function extractHashtags(body: string): string[] {
  const names = new Set<string>()
  let m: RegExpExecArray | null
  HASHTAG_RE.lastIndex = 0
  while ((m = HASHTAG_RE.exec(body))) names.add(m[1])
  return [...names]
}

/** Resolve tag names to ids, creating any that don't already exist. */
export async function resolveTagIds(names: string[]): Promise<number[]> {
  if (!names.length) return []
  const store = useTagsStore()
  if (!store.tags.length) await store.fetchTree()
  const byLower = new Map(store.tags.map((t) => [t.name.toLowerCase(), t.id]))
  const ids: number[] = []
  let created = false
  for (const name of names) {
    const existing = byLower.get(name.toLowerCase())
    if (existing != null) {
      ids.push(existing)
      continue
    }
    const tag = await tagsApi.create({ name })
    byLower.set(name.toLowerCase(), tag.id)
    ids.push(tag.id)
    created = true
  }
  if (created) await store.fetchTree()
  return ids
}
