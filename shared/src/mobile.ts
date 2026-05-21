/**
 * MobileProvider — direct SQLite access via @capacitor-community/sqlite.
 *
 * This module is only imported when running inside Capacitor (mobile).
 * It replicates the backend CRUD operations in TypeScript, talking
 * directly to a local SQLite database.
 *
 * PREREQUISITES:
 *   - @capacitor-community/sqlite installed
 *   - Database initialized and schema migrated before use
 */
import { CapacitorSQLite } from '@capacitor-community/sqlite'
import type { PlatformProvider } from './platform'

// ── Helpers ───────────────────────────────────────────────────────────

interface Row { [col: string]: any }

async function query(sql: string, params: any[] = []): Promise<Row[]> {
  const { values } = await CapacitorSQLite.query({ statement: sql, values: params })
  return values ?? []
}

async function run(sql: string, params: any[] = []): Promise<void> {
  await CapacitorSQLite.run({ statement: sql, values: params })
}

// ── Schema bootstrap ──────────────────────────────────────────────────

const SCHEMA = `
CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  parent_id INTEGER REFERENCES tags(id)
);
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_date TEXT NOT NULL,
  title TEXT,
  body TEXT NOT NULL DEFAULT '',
  is_deleted INTEGER NOT NULL DEFAULT 0,
  is_encrypted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS entry_tags (
  entry_id INTEGER REFERENCES entries(id) ON DELETE CASCADE,
  tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (entry_id, tag_id)
);
CREATE TABLE IF NOT EXISTS media (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL,
  file_size INTEGER NOT NULL DEFAULT 0,
  caption TEXT,
  blob BLOB,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  is_builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(title, body, content=entries, content_rowid=id);
`

export async function initMobileDb(dbName: string = 'diarilinux'): Promise<void> {
  const { result } = await CapacitorSQLite.isDatabase({ database: dbName })
  if (!result) {
    await CapacitorSQLite.createConnection({ database: dbName })
  }
  await CapacitorSQLite.open({ database: dbName })
  // Run schema creation statements
  for (const stmt of SCHEMA.split(';').map(s => s.trim()).filter(Boolean)) {
    await run(stmt)
  }
  // Seed built-in templates
  const rows = await query('SELECT COUNT(*) as cnt FROM templates WHERE is_builtin = 1')
  if ((rows[0]?.cnt ?? 0) === 0) {
    await run(`INSERT INTO templates (name, body, is_builtin) VALUES (?, ?, 1)`, ['Daily Reflection', "## How I'm feeling\n\n\n## What I did today\n\n\n## Grateful for\n\n"])
    await run(`INSERT INTO templates (name, body, is_builtin) VALUES (?, ?, 1)`, ['Gratitude Journal', '## Three things I\'m grateful for\n\n1. \n2. \n3. \n\n## Why\n\n'])
    await run(`INSERT INTO templates (name, body, is_builtin) VALUES (?, ?, 1)`, ['Travel Log', '## Location\n\n\n## Highlights\n\n\n## Photos & Memories\n\n'])
    await run(`INSERT INTO templates (name, body, is_builtin) VALUES (?, ?, 1)`, ['Weekly Review', '## Wins this week\n\n\n## Challenges\n\n\n## Goals for next week\n\n'])
  }
}

// ── Provider implementation ───────────────────────────────────────────

export const mobileProvider: PlatformProvider = {
  entries: {
    async create(data) {
      const r = await run('INSERT INTO entries (entry_date, title, body) VALUES (?, ?, ?)',
        [data.entry_date, data.title ?? null, data.body])
      const rows = await query('SELECT * FROM entries WHERE id = last_insert_rowid()')
      return rows[0] as any
    },
    async get(id) {
      const rows = await query('SELECT * FROM entries WHERE id = ? AND is_deleted = 0', [id])
      return rows[0] as any
    },
    async list(params?) {
      let sql = 'SELECT * FROM entries WHERE is_deleted = 0'
      const p: any[] = []
      if (params?.year) { sql += ' AND CAST(strftime("%Y", entry_date) AS INTEGER) = ?'; p.push(params.year) }
      if (params?.month) { sql += ' AND CAST(strftime("%m", entry_date) AS INTEGER) = ?'; p.push(params.month) }
      if (params?.tag_ids?.length) {
        sql += ` AND id IN (SELECT entry_id FROM entry_tags WHERE tag_id IN (${params.tag_ids.map(() => '?').join(',')}))`
        p.push(...params.tag_ids)
      }
      const totalRows = await query(`SELECT COUNT(*) as total FROM (${sql})`, p)
      const total = totalRows[0]?.total ?? 0
      sql += ' ORDER BY entry_date DESC'
      if (params?.offset != null) { sql += ' LIMIT ? OFFSET ?'; p.push(params.limit ?? 50, params.offset) }
      const items = await query(sql, p) as any[]
      return { items, total, offset: params?.offset ?? 0, limit: params?.limit ?? 50 }
    },
    async update(id, data) {
      const sets: string[] = []; const p: any[] = []
      if (data.title !== undefined) { sets.push('title = ?'); p.push(data.title) }
      if (data.body !== undefined) { sets.push('body = ?'); p.push(data.body) }
      if (sets.length) { sets.push("updated_at = datetime('now')"); p.push(id); await run(`UPDATE entries SET ${sets.join(', ')} WHERE id = ?`, p) }
      if (data.tag_ids) {
        await run('DELETE FROM entry_tags WHERE entry_id = ?', [id])
        for (const tid of data.tag_ids) await run('INSERT INTO entry_tags (entry_id, tag_id) VALUES (?, ?)', [id, tid])
      }
      return (await query('SELECT * FROM entries WHERE id = ?', [id]))[0] as any
    },
    async delete(id) { await run('UPDATE entries SET is_deleted = 1, updated_at = datetime("now") WHERE id = ?', [id]) },
    async importEntries(entries) {
      let imported = 0, skipped = 0
      for (const e of entries) {
        const existing = await query('SELECT id FROM entries WHERE entry_date = ? AND title = ?', [e.entry_date, e.title ?? ''])
        if (existing.length) { skipped++; continue }
        await run('INSERT INTO entries (entry_date, title, body) VALUES (?, ?, ?)', [e.entry_date, e.title ?? null, e.body])
        imported++
      }
      return { imported, skipped }
    },
    async importFile(_file) { throw new Error('File import not supported on mobile') },
    async resetDatabase() { await run('DELETE FROM entries'); await run('DELETE FROM entry_tags'); await run('DELETE FROM media'); return { status: 'ok', message: 'Database reset' } },
    async deduplicate() { return { groups_found: 0, duplicates_removed: 0 } },
    async calendarMonth(year, month) {
      return query('SELECT * FROM entries WHERE is_deleted = 0 AND strftime("%Y-%m", entry_date) = ? ORDER BY entry_date', [`${year}-${String(month).padStart(2, '0')}`]) as any
    },
    async search(query, offset = 0, limit = 20) {
      const rows = await query('SELECT e.*, snippet(entries_fts, 0, "<mark>", "</mark>") as snippet, rank FROM entries_fts f JOIN entries e ON e.id = f.rowid WHERE entries_fts MATCH ? AND e.is_deleted = 0 ORDER BY rank LIMIT ? OFFSET ?', [query, limit, offset])
      const totalRows = await query('SELECT COUNT(*) as total FROM entries_fts f JOIN entries e ON e.id = f.rowid WHERE entries_fts MATCH ? AND e.is_deleted = 0', [query])
      return { items: rows as any[], total: totalRows[0]?.total ?? 0, offset, limit }
    },
    exportMarkdownUrl() { return '' },
  },

  tags: {
    async create(data) { await run('INSERT INTO tags (name, parent_id) VALUES (?, ?)', [data.name, data.parent_id ?? null]); return (await query('SELECT * FROM tags WHERE id = last_insert_rowid()'))[0] as any },
    async list() { return query('SELECT * FROM tags ORDER BY name') as any },
    async tree() { return query('SELECT * FROM tags ORDER BY name') as any },
    async update(id, data) { await run('UPDATE tags SET name = ? WHERE id = ?', [data.name, id]); return (await query('SELECT * FROM tags WHERE id = ?', [id]))[0] as any },
    async delete(id) { await run('DELETE FROM tags WHERE id = ?', [id]) },
  },

  templates: {
    async list() { return query('SELECT * FROM templates ORDER BY name') as any },
    async create(data) { await run('INSERT INTO templates (name, body) VALUES (?, ?)', [data.name, data.body]); return (await query('SELECT * FROM templates WHERE id = last_insert_rowid()'))[0] as any },
    async update(id, data) { const sets: string[] = []; const p: any[] = []; if (data.name) { sets.push('name = ?'); p.push(data.name) } if (data.body) { sets.push('body = ?'); p.push(data.body) } if (sets.length) { sets.push("updated_at = datetime('now')"); p.push(id); await run(`UPDATE templates SET ${sets.join(', ')} WHERE id = ?`, p) } return (await query('SELECT * FROM templates WHERE id = ?', [id]))[0] as any },
    async remove(id) { await run('DELETE FROM templates WHERE id = ? AND is_builtin = 0', [id]) },
  },

  media: {
    async upload(entryId, file, caption) {
      const buf = await file.arrayBuffer()
      await run('INSERT INTO media (entry_id, filename, media_type, file_size, caption, blob) VALUES (?, ?, ?, ?, ?, ?)',
        [entryId, file.name, file.type, file.size, caption ?? null, new Uint8Array(buf)])
      return (await query('SELECT id, entry_id, filename, media_type, file_size, caption, created_at FROM media WHERE id = last_insert_rowid()'))[0] as any
    },
    async get(id) { return (await query('SELECT id, entry_id, filename, media_type, file_size, caption, created_at FROM media WHERE id = ?', [id]))[0] as any },
    fileUrl(id) { return `sqlite://media/${id}` },
    async delete(id) { await run('DELETE FROM media WHERE id = ?', [id]) },
    async listByEntry(entryId) { return query('SELECT id, entry_id, filename, media_type, file_size, caption, created_at FROM media WHERE entry_id = ?', [entryId]) as any },
  },

  recordings: {
    async upload() { throw new Error('Recordings not supported on mobile') },
    async listByEntry() { return [] as any },
    async transcribe() { throw new Error('Transcription not supported on mobile') },
    async get() { throw new Error('Not supported on mobile') },
    async delete() { throw new Error('Not supported on mobile') },
  },

  search: {
    async global(query, params) {
      let sql = `SELECT e.*, snippet(entries_fts, 0, '<mark>', '</mark>') as snippet, rank
                 FROM entries_fts f JOIN entries e ON e.id = f.rowid
                 WHERE entries_fts MATCH ? AND e.is_deleted = 0`
      const p: any[] = [query]
      if (params?.date_from) { sql += ' AND e.entry_date >= ?'; p.push(params.date_from) }
      if (params?.date_to) { sql += ' AND e.entry_date <= ?'; p.push(params.date_to) }
      sql += ' ORDER BY rank LIMIT ? OFFSET ?'
      p.push(params?.limit ?? 20, params?.offset ?? 0)
      const items = await query(sql, p) as any[]
      return { items, total: items.length, offset: params?.offset ?? 0, limit: params?.limit ?? 20 }
    },
  },

  ai: {
    async grammarCheck() { throw new Error('AI not available on mobile') },
    async spellCheck() { throw new Error('AI not available on mobile') },
    async rewrite() { throw new Error('AI not available on mobile') },
    async status() { return { ollama_available: false, model_name: '', model_loaded: false, error: 'Mobile — no AI backend' } },
  },

  tts: {
    getVoice() { return '' },
    entryUrl() { return '' },
    async speakBlob() { throw new Error('TTS not available on mobile') },
  },

  revisions: {
    async list() { return { items: [], total: 0, offset: 0, limit: 50 } },
    async get() { throw new Error('Revisions not supported on mobile') },
    async diff() { throw new Error('Revisions not supported on mobile') },
    async restore() { throw new Error('Revisions not supported on mobile') },
  },

  geotag: {
    async set(entryId, data) {
      await run('UPDATE entries SET latitude = ?, longitude = ?, location_name = ? WHERE id = ?',
        [data.latitude, data.longitude, data.location_name ?? null, entryId])
      return { entry_id: entryId, latitude: data.latitude, longitude: data.longitude, location_name: data.location_name ?? null }
    },
    async remove(entryId) {
      await run('UPDATE entries SET latitude = NULL, longitude = NULL, location_name = NULL WHERE id = ?', [entryId])
    },
    async mapView() { return query('SELECT id as entry_id, latitude, longitude, location_name, entry_date, title FROM entries WHERE latitude IS NOT NULL AND is_deleted = 0') as any },
    async nearby(lat, lon, radiusKm = 10, limit = 20) {
      const rows = await query(
        `SELECT id as entry_id, entry_date, title, latitude, longitude, location_name,
                (6371 * acos(cos(radians(?)) * cos(radians(latitude)) * cos(radians(longitude) - radians(?)) + sin(radians(?)) * sin(radians(latitude)))) AS distance_km
         FROM entries WHERE latitude IS NOT NULL AND is_deleted = 0 AND distance_km <= ? ORDER BY distance_km LIMIT ?`,
        [lat, lon, lat, radiusKm, limit])
      return { items: rows as any[], total: rows.length }
    },
  },

  reminders: {
    async create(data) { throw new Error('Reminders not yet implemented on mobile') },
    async list() { return [] as any },
    async update() { throw new Error('Not supported on mobile') },
    async delete() { throw new Error('Not supported on mobile') },
    async testNotification() { throw new Error('Not supported on mobile') },
  },

  analytics: {
    async overview() {
      const e = (await query('SELECT COUNT(*) as cnt FROM entries WHERE is_deleted = 0'))[0]
      const w = (await query("SELECT COALESCE(SUM(LENGTH(body) - LENGTH(REPLACE(body, ' ', '')) + 1), 0) as words FROM entries WHERE is_deleted = 0"))[0]
      return { total_entries: e?.cnt ?? 0, total_words: w?.words ?? 0, total_media: 0, total_recordings: 0, date_range_start: null, date_range_end: null, longest_streak: 0, current_streak: 0 }
    },
    async habits() { return [] as any },
    async words() { return { total_words: 0, average_words_per_entry: 0, longest_entry_words: 0, shortest_entry_words: 0 } },
    async tagStats() { return [] as any },
    async heatmap() { return { year: new Date().getFullYear(), days: [] } },
    async mediaStats() { return { total_images: 0, total_videos: 0, total_recordings: 0, total_size_bytes: 0 } },
  },

  export: {
    async html() { throw new Error('Export not supported on mobile') },
    pdfUrl() { return '' },
  },
}
