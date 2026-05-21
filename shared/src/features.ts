/**
 * Feature flags — desktop-only features are disabled on mobile (Capacitor).
 *
 * Set `VITE_PLATFORM=capacitor` in the mobile build to toggle.
 */

const isMobile = typeof window !== 'undefined'
  && (import.meta.env.VITE_PLATFORM === 'capacitor'
    || !!(window as any).Capacitor)

export const FEATURES = {
  /** Tesseract OCR — desktop only */
  ocr: !isMobile,
  /** Whisper voice-to-text — desktop only */
  whisper: !isMobile,
  /** WeasyPrint PDF export — desktop only */
  pdf: !isMobile,
  /** TTS via edge-tts — desktop only */
  tts: !isMobile,
  /** Ollama AI assistance — desktop only */
  ai: !isMobile,
  /** Cloud sync — desktop only (relies on Python backend) */
  sync: !isMobile,

  // ── Available everywhere ────────────────────────────────────────────
  templates: true,
  markdown: true,
  search: true,
  media: true,
  geotag: true,
  reminders: true,
  analytics: true,
  revisions: true,
  tags: true,
}
