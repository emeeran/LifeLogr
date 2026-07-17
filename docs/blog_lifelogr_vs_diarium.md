# LifeLogr vs Diarium: A Privacy-First, Linux-Native Take on Journaling

If you've ever kept a journal on Windows, Android, or iOS, chances are you've stumbled across **Diarium** — one of the most beloved cross-platform journaling apps out there. It's rich, calendar-driven, and lets you attach photos, audio, mood ratings, and tags to daily entries. It's great. But there's a catch: Diarium is closed-source, Windows/Android-first, and its Linux story is essentially "run it in a browser, maybe."

That gap is exactly why I built **LifeLogr**.

LifeLogr is an open, privacy-first, offline-first daily journaling app engineered for Linux (Ubuntu 24.x LTS) — with the same everyday writing experience as Diarium, but with the keys to the kingdom in your hands. This post compares the two and walks through LifeLogr's features and architecture.

---

## How LifeLogr Compares to Diarium

| Capability | Diarium | LifeLogr |
|---|---|---|
| Calendar-bound daily entries | ✅ | ✅ |
| Markdown writing | Partial | ✅ First-class |
| Media attachments (images/video/docs) | ✅ | ✅ (25 MB / file) |
| Voice recording + transcription | ✅ (cloud STT) | ✅ **Local** Whisper transcription |
| Mood & sentiment tracking | ✅ | ✅ |
| Tags (hierarchical) | ✅ | ✅ |
| Daily prompts | ✅ | ✅ |
| AI grammar / insight assistance | ❌ | ✅ Local Ollama |
| Semantic + FTS5 hybrid search | ❌ | ✅ |
| End-to-end encrypted cloud backup | Partial | ✅ Google Drive / OneDrive / Dropbox |
| Open source & self-hostable | ❌ | ✅ |
| Native Linux packaging | ❌ | ✅ Tauri `.deb` / AppImage |

The headline difference: **where Diarium leans on cloud services for transcription and AI, LifeLogr keeps every model on-device.** Your voice memos are transcribed by a local Whisper model. Your grammar suggestions come from Ollama running on your machine. No journal text ever leaves your laptop unless you explicitly push an encrypted backup.

---

## Features at a Glance

- **Date-bound journaling** — one entry per calendar day, soft-deleted (never hard-destroyed), with full markdown bodies.
- **Rich media** — inline images, video notes, and document attachments, all managed by a media service that cleans up files on soft delete.
- **Voice notes** — record, then transcribe locally with Whisper; transcribed text can be appended straight to the entry body.
- **AI tools** — a registry-driven AI system powering grammar checks, mood insights, and reflection prompts, all via a local Ollama instance.
- **Hybrid search** — SQLite FTS5 for keyword search plus semantic vector search (embeddings) for "find me entries that feel like this."
- **Reminders & prompts** — APScheduler-driven cron jobs with offline catch-up, so reminders fire even if your laptop was asleep.
- **Encrypted cloud sync** — incremental, end-to-end encrypted backups to Google Drive, OneDrive, or Dropbox, with atomic restore.
- **Templates** — reusable entry templates for daily standups, gratitude logs, trip logs, and more.
- **Analytics** — mood trends, writing streaks, and tag distributions rendered in accessible Vue dashboards.

---

## Architecture

LifeLogr is a layered, multi-platform application:

```
┌─────────────────────────────────────────────────┐
│  Desktop Shell (Tauri v2 / Rust)                 │
│  ┌────────────────────┐  ┌────────────────────┐  │
│  │ Vue 3 SPA          │  │ Python sidecar     │  │
│  │ Vite + TS + Pinia  │  │ FastAPI backend    │  │
│  │ TailwindCSS v4     │◄─┤ SQLAlchemy + SQLite│  │
│  └────────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────┘
```

**Backend (`backend/`)**
- **FastAPI** async server with **Pydantic v2** schemas.
- **SQLAlchemy 2.x** over **SQLite in WAL mode** with foreign keys enforced. Schema migrations are inline and idempotent — no Alembic, no drift.
- Layered routers → services → models, with one service per bounded context (Journal, Tagging, Media, Voice, Backup, Analytics, Sync, Reminders, Search).
- Local ML integrations: **Ollama** for embeddings and AI tools, **Whisper** for transcription, **Tesseract** for OCR on attached images.

**Frontend (`frontend/`)**
- **Vue 3** single-page app built with Vite, TypeScript, Pinia, and TailwindCSS v4.
- A registry-driven AI tool system — the drawer, context menu, and composable all iterate one config, so adding a tool is a one-liner.
- Accessible (WCAG-minded) dashboard, timeline, map, and calendar views.

**Desktop wrapper (`desktop/`)**
- **Tauri v2** Rust app that bundles the Vue frontend and ships the Python backend as a packaged sidecar, producing a native `.deb` and AppImage.
- The frontend build injects `VITE_APP_VERSION` from `Cargo.toml`, so the About tab and the bundle filename always agree.

**Mobile (`mobile/`)**
- Capacitor scaffolding for a future iOS/Android port.

---

## Why This Matters

Diarium proved there's real demand for a *daily, calendar-driven, media-rich* journaling experience. LifeLogr takes that proven UX and puts it on a foundation that respects your data:

- **Offline-first** — the app is fully usable with no network. Sync is an opt-in side-channel.
- **Local AI** — transcription and language assistance run on your hardware, not a third-party API.
- **Encrypted backups** — your journal is recoverable without ever being readable by your cloud provider.
- **Open architecture** — a plugin system, FTS5 + semantic search, and a clean SDD-documented codebase (150 passing tests) make it straightforward to extend.

If you've been holding out for "Diarium, but on Linux, and open, and private" — LifeLogr is for you.

---

*Want to try it? Clone the repo, `make setup`, then `make run`. The full spec-driven design docs live under `docs/` if you'd like to read the architecture in depth.*
