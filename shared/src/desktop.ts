/**
 * DesktopProvider — delegates to the existing HTTP-based API modules.
 *
 * On desktop (Tauri), the Python FastAPI backend runs as a sidecar on localhost.
 * The existing `frontend/src/api/*.ts` modules already implement all the calls
 * via fetch, so this provider simply re-exports them under the PlatformProvider
 * interface.
 */
import type { PlatformProvider } from './platform'

import { entriesApi } from '../../frontend/src/api/entries'
import { tagsApi } from '../../frontend/src/api/tags'
import { templatesApi } from '../../frontend/src/api/templates'
import { mediaApi } from '../../frontend/src/api/media'
import { recordingsApi } from '../../frontend/src/api/recordings'
import { globalSearch } from '../../frontend/src/api/search'
import { grammarCheck, spellCheck, rewrite, aiStatus } from '../../frontend/src/api/ai'
import { ttsApi } from '../../frontend/src/api/tts'
import { listRevisions, getRevision, diffRevisions, restoreRevision } from '../../frontend/src/api/revisions'
import { setGeotag, removeGeotag, mapView, nearbyEntries } from '../../frontend/src/api/geotagging'
import { createReminder, listReminders, updateReminder, deleteReminder, testNotification } from '../../frontend/src/api/reminders'
import { getOverview, getHabits, getWords, getTagStats, getHeatmap, getMediaStats } from '../../frontend/src/api/analytics'
import { exportHtml, getExportPdfUrl } from '../../frontend/src/api/export'

export const desktopProvider: PlatformProvider = {
  entries: entriesApi,
  tags: tagsApi,
  templates: templatesApi,
  media: mediaApi,
  recordings: recordingsApi,
  search: { global: globalSearch },
  ai: { grammarCheck, spellCheck, rewrite, status: aiStatus },
  tts: ttsApi,
  revisions: { list: listRevisions, get: getRevision, diff: diffRevisions, restore: restoreRevision },
  geotag: { set: setGeotag, remove: removeGeotag, mapView, nearby: nearbyEntries },
  reminders: { create: createReminder, list: listReminders, update: updateReminder, delete: deleteReminder, testNotification },
  analytics: { overview: getOverview, habits: getHabits, words: getWords, tagStats: getTagStats, heatmap: getHeatmap, mediaStats: getMediaStats },
  export: { html: exportHtml, pdfUrl: getExportPdfUrl },
}
