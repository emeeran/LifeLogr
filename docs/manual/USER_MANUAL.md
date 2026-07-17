# LifeLogr — User Manual

> **Privacy-first, offline-first journaling for Linux (Ubuntu 24.04).**
> All your data stays on your machine. AI runs locally via Ollama; OCR via Tesseract; read-aloud via Edge TTS.

*Version 0.7.0*

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Interface Overview](#2-interface-overview)
3. [Desktop vs Web — Which Build Are You In?](#3-desktop-vs-web--which-build-are-you-in)
4. [Journal Entries](#4-journal-entries)
5. [Notes Mode](#5-notes-mode)
6. [Clipping & OCR (Screen-Snip / Web-Clip)](#6-clipping--ocr-screen-snip--web-clip)
7. [Templates](#7-templates)
8. [Tags](#8-tags)
9. [Markdown Reference](#9-markdown-reference)
10. [Search](#10-search)
11. [Calendar & Timeline Views](#11-calendar--timeline-views)
12. [Media & Attachments](#12-media--attachments)
13. [Voice Recording](#13-voice-recording)
14. [Read Aloud (TTS)](#14-read-aloud-tts)
15. [AI Writing Assistant](#15-ai-writing-assistant)
16. [Reminders](#16-reminders)
17. [Planner (Tasks)](#17-planner-tasks)
18. [Contacts](#18-contacts)
19. [Email](#19-email)
20. [Dashboard & Analytics](#20-dashboard--analytics)
21. [Encryption](#21-encryption)
22. [Export & Import](#22-export--import)
23. [Backup & Cloud Sync](#23-backup--cloud-sync)
24. [Google Calendar & Tasks Sync](#24-google-calendar--tasks-sync)
25. [Settings](#25-settings)
26. [Keyboard Shortcuts](#26-keyboard-shortcuts)
27. [Troubleshooting](#27-troubleshooting)
28. [Data, Privacy & File Locations](#28-data-privacy--file-locations)

---

## 1. Getting Started

### System requirements
- **Linux:** Ubuntu 24.04 LTS (or equivalent modern distro), Python 3.11+ (web build only), glibc.
- **Optional, for AI/OCR:** [Ollama](https://ollama.com) (text AI), Tesseract (OCR — auto-installed by the `.deb`).
- A working microphone (for voice recording) and speakers/headphones (for read-aloud).

### Install the desktop app (Tauri)
A native window with everything bundled. **Required if you want screen-snipping.**
```bash
sudo dpkg -i LifeLogr_0.7.0_amd64.deb
sudo apt-get install -f
```
Launch **LifeLogr** from your app menu.

### Install the web app (browser)
Lighter; the backend serves the app and you use it in a browser tab. The Python virtualenv is built on your machine during install (needs network).
```bash
sudo dpkg -i lifelogr-web_0.7.0_amd64.deb
sudo apt-get install -f
```
Launch **LifeLogr** from your app menu (or run `lifelogr`). It opens a browser tab on a free local port. Stop it with `lifelogr --stop`.

> **Upgrading:** fully **quit** the running app before relaunching (closing the window may leave the old process alive). Web app: `lifelogr --stop`.

### First launch
1. The sidebar lists the main areas: **Dashboard, Journal, Timeline, Notes, Reminders, Planner, Contacts, Email, Media**.
2. Open **Journal** to write a dated entry, or **Notes** for standalone notebooks.
3. (Optional) Go to **Settings → AI**, set your Ollama model (a CPU-friendly model like `gemma3:4b` is recommended) to enable the AI features.

---

## 2. Interface Overview

```
┌──────────┬──────────────────────────────────────┐
│ Sidebar  │   Active view (Journal / Notes /     │
│ (nav +   │   Planner / Email / Dashboard …)     │
│  search) │   plus an editor panel on the right  │
│          │   for entries and notes              │
└──────────┴──────────────────────────────────────┘
```

- **Sidebar** — navigation between modes. You can reorder the nav items by dragging. At the bottom: theme toggle and **Settings**.
- **Search** — press `Ctrl+K` anywhere to open the global search palette.
- **Editor panel** — when you open a journal entry or a note, it appears on the right with a title field, a markdown formatting toolbar (collapsible), the body, and a bottom action bar (tags, media, AI tools, read-aloud, save).

---

## 3. Desktop vs Web — Which Build Are You In?

| Capability | Desktop (Tauri) | Web (browser) |
|---|:---:|:---:|
| Screen-snippet (`Ctrl+Shift+S` / ✂️) | ✅ | ❌ |
| Web-clip text (🌐) | ✅ | ✅ |
| OCR | ✅ (auto after a snip) | endpoint exists; no in-app button¹ |
| Voice recording | ✅ | ✅ |
| All other features (AI, encryption, sync, etc.) | ✅ | ✅ |
| **Data directory** | `~/.local/share/com.lifelogr.desktop/` | `~/.local/share/lifelogr/` |

¹ The two builds use **separate databases** by default. To share one journal between them, point one build at the other's data directory via **Settings → Data & Backup → Storage location** (and copy the `.secret_key` so encrypted items still decrypt).

---

## 4. Journal Entries

Journal entries are **date-bound** (one per day, by default).

### Create an entry
- Click a day in the **Calendar**, or use the **new entry** action.
- A new entry for that date opens in the editor. If you've set a **default template**, its content is pre-filled.

### Entry fields
- **Title** — optional heading.
- **Date** — the entry's date.
- **Mood** — a short mood label (shown on the dashboard's mood distribution).
- **Body** — markdown (see [§9](#9-markdown-reference)).
- **Summary** — a one-line summary (can be AI-generated; see [§15](#15-ai-writing-assistant)).
- **Tags** — assign tags (see [§8](#8-tags)).
- **Location** — optional latitude/longitude/place name (geotag data; stored for future map features).
- **Media** — attach images/audio/video/documents (see [§12](#12-media--attachments)).

### Saving
- Press **`Ctrl+S`** or click **Save**. A status indicator shows when a save is in progress/complete.
- **Notes** use manual save (see [§5](#5-notes-mode)); journal entries save on demand and on navigate.

### Formatting toolbar
Bold, italic, strikethrough, inline code, code block, link, headings, bullet/numbered lists, checklists, blockquote, alignment, tables, emoji, find & replace — plus **AI tools** and (in Notes) the **clip** buttons. See [§26](#26-keyboard-shortcuts) for shortcuts.

---

## 5. Notes Mode

Notes are standalone, non-date-bound documents organized into **notebooks**.

### Structure
- **Notebooks** (folders) — create them in the left tree; each can have a color.
- **Notes** — belong to a notebook; can be **pinned** and **color-coded**.
- **Pages** — each note has tabbed pages (like sections). Add/rename/reorder/delete pages.

### The editor
- Full markdown editor (shared with journal entries): formatting toolbar, live preview, find & replace.
- **Manual save** — Notes do **not** autosave as you type. Click **Save** (or leave the note) to persist. *Switching to another note without saving discards the outgoing note's edits.*
- On opening **Notes**, a **fresh blank note** is created and opened automatically (ready to write or clip).

### Embedding media
- Drag-and-drop, paste, or use the embed (🖼️/🎵/🎬) buttons. In the desktop app you can also drop a file from your file manager (native path import).
- Embedded images are shown resizable in the preview.

### Encrypting a note
See [§21](#21-encryption).

### Searching notes
Notes are included in the global search palette (`Ctrl+K`) and have their own FTS5 search.

---

## 6. Clipping & OCR (Screen-Snip / Web-Clip)

Capture content into a note, embed it as a picture, and read its text with OCR.

### Screen snip (desktop app only)
1. Open a **non-encrypted note** in Notes mode.
2. Trigger a snip:
   - **`Ctrl+Shift+S`** (works from anywhere), or
   - the **✂️ scissors** button in the formatting toolbar.
3. The app hides itself, captures the screen, then shows the capture in a full-screen **crop overlay**. *(On Wayland, approve the screen-capture portal prompt the first time.)*
4. **Drag a rectangle** over the region you want and release.
5. The cropped image is **embedded into the note**, then **OCR runs automatically** and the recognized text is inserted beneath the image in a collapsible `📷 OCR` block — and becomes **searchable**.

> Browsers can't capture your screen, so the snip is **desktop-only**. If `Ctrl+Shift+S` does nothing, another app may have grabbed that key — use the ✂️ toolbar button.

### Web-clip (both builds)
- Click the **🌐 globe** button and enter a URL.
- LifeLogr fetches the page **server-side** and inserts its main text as markdown.
- The fetch is **SSRF-hardened** (internal/loopback addresses are blocked on every hop, including redirects).
- On the desktop app the page text is inserted the same way; OCR applies to images you snip, not to web-clipped text (it's already text).

### OCR requirements
- **Tesseract** must be installed (the `.deb` declares it as a dependency; if missing, OCR returns a helpful error with install instructions).
- OCR works on any embedded image via the OCR endpoint; in the UI it's triggered automatically by a snip.

---

## 7. Templates

Templates pre-fill new entries with structured markdown.

- **Built-in templates** ship with the app (e.g., daily reflection, gratitude) and can't be edited.
- **Custom templates** — create your own from the template picker (name + markdown body).
- **Apply** — when creating an entry, pick a template to pre-fill; for an existing entry, applying a template appends its content.
- **Default template** — set in Settings so every new entry starts with that template.

---

## 8. Tags

Tags are shared across journal entries and notes, and support **hierarchy** (parent → child).

- **Assign** — open the tag panel in the editor; click tags to toggle, or type to create a new one (optionally under a parent).
- **Filter** — use tags to narrow the calendar/timeline and the search palette (click tag pills).
- **Manage** — rename or delete tags; changes propagate to all tagged entries/notes.

---

## 9. Markdown Reference

LifeLogr renders **GitHub-Flavored Markdown** in the preview pane (sanitized via DOMPurify).

```markdown
**bold**  *italic*  ~~strike~~  `code`

# Heading 1
## Heading 2
### Heading 3

- bullet
- another

1. first
2. second

- [x] done
- [ ] todo

> blockquote

[link](https://example.com)
![image](image-url)

| A | B |
|---|---|
| 1 | 2 |
```

- Horizontal rule: type `---` or use the toolbar.
- Embedded media (uploaded via the app) is inserted as `![name](/api/v1/.../file)` and rendered inline; audio/video get inline players.

---

## 10. Search

Press **`Ctrl+K`** to open the global search palette.

### Three modes
| Mode | What it does |
|---|---|
| **Keyword** (`Aa`) | Full-text search (SQLite FTS5, BM25-ranked) across titles and bodies. |
| **Semantic** (`AI`) | Meaning-based search using local embeddings (`nomic-embed-text`). Finds conceptually similar content without exact words. |
| **Hybrid** (`Mix`, default) | Combines keyword + semantic via Reciprocal Rank Fusion. |

### Scope & filters
- Results span **entries, notes, and tasks** in one stream.
- Filter by **mood**, **tags**, and **date range**.
- Navigate with `↑`/`↓`, open with `Enter`, close with `Esc`.

> Semantic/hybrid modes need the embedding model. Pull it from **Settings → AI** or run `ollama pull nomic-embed-text`.

---

## 11. Calendar & Timeline Views

- **Calendar (Journal)** — month grid; days with entries are marked. Click a day to open/create that day's entry. Filter by tag.
- **Timeline** — reverse-chronological list of entries with previews; click to open.

---

## 12. Media & Attachments

- **Supported:** images (JPG/PNG/GIF/WebP/BMP/TIFF), audio (MP3/WAV/OGG/M4A…), video (MP4/WebM/MOV), PDF, CSV, text. Max **25 MB** per file.
- **Attach** — drag-and-drop, paste, the embed buttons, or (desktop) drop a file from your file manager.
- **Gallery (Media mode)** — browse all media across entries; timeline view and global-search integration.
- Images are auto-compressed to WebP for storage; original quality is preserved where it matters for OCR.
- Inline images in notes are resizable in the preview.

---

## 13. Voice Recording

> **Note:** LifeLogr records audio (via the system microphone). **Speech-to-text transcription was removed** in a recent release — recordings are stored as audio attachments only.

- Click the **microphone** in the editor's bottom bar (desktop: granted automatically; grant permission if prompted).
- A timer shows while recording; click **Stop** to save the clip to the entry.
- Playback inline; delete unwanted clips.
- On Linux, recording needs GStreamer plugins (the desktop `.deb` depends on them).

---

## 14. Read Aloud (TTS)

- Select text (or open an entry/note) and choose **Read aloud**.
- Audio is generated locally-cached via **Microsoft Edge TTS** (`edge-tts`) and streamed with seek support.
- Configure **voice, rate, volume, and pitch** in **Settings → Features → Read Aloud** (the setting persists).
- The TTS cache lives under `<data-dir>/tts/`.

---

## 15. AI Writing Assistant

All AI runs **locally via Ollama** — nothing is sent to the cloud. Requires Ollama running and a model set in **Settings → AI**.

### On-demand tools (select text → AI / right-click menu)
- **Grammar check**, **Spell check**
- **Rewrite** (with style options)
- **Change tone**, **Expand**, **Clarity**
- **Summarize**, **Key points**, **Action items**
- **Shorten**, **Simplify**, **Polish**
- **Translate** (pick a language)
- **Add structure**, **Generate title**
- **Define**, **Voice** (active/passive)

Each result can be **Replaced**, **Inserted**, or **Copied**.

### Automatic analysis (runs in the background after you save)
- **Summary** — a one-line summary (shown in timeline/search previews).
- **Sentiment** — primary/secondary emotion + valence (powers the mood timeline on the dashboard).
- **Reflection prompts** — questions to reflect further (shown on the entry).
- **Tag suggestions** — suggested tags appear as pills; click to add.
- **Themes** — recurring topics detected across your writing.
- **Continue writing** — a writer's-block helper that suggests a continuation.

### Feature toggles
Enable/disable each AI feature individually in **Settings → AI / Features** (embeddings, tag suggestions, sentiment, summarization, reflection prompts, writer's-block helper). If Ollama is unavailable, everything degrades gracefully — saving still works.

> **CPU tip:** avoid "thinking" models (they can hang on CPU). `gemma3:4b` works well.

---

## 16. Reminders

- Create time-based reminders (title, optional message, time, days of the week).
- **Enable/disable**, edit, **test** (preview the notification), or delete.
- Reminders fire while the app is running and show a desktop notification; clicking it focuses LifeLogr.

---

## 17. Planner (Tasks)

- Organize work into **task lists** with **tasks** (and subtasks); mark complete, reorder.
- Optionally **sync with Google Tasks** (two-way) — see [§24](#24-google-calendar--tasks-sync).
- Tasks are included in global search.

---

## 18. Contacts

- A full **address book**: contacts with names, emails, phones, photos, notes.
- Group contacts (**Contact groups**), mark **favorites**, and search/filter.
- **Import/Export vCard** (`.vcf`).
- Contacts can be linked to email messages.

---

## 19. Email

A built-in **IMAP/SMTP** client.

- Add multiple **email accounts**; folders are auto-detected (INBOX, Sent, Trash, Junk, …).
- Read threaded conversations; **compose and send** with attachments.
- **Spam blocking** with a blocklist and rules.
- Email is included in the app's navigation as its own mode.

---

## 20. Dashboard & Analytics

The **Dashboard** shows insights about your journaling:

- **Overview** — total entries, total words, total media, longest/current streaks, date range.
- **Writing habits** — day-of-week frequency + a GitHub-style **heatmap**.
- **Word stats** — averages, longest/shortest entries.
- **Tag stats** — most-used tags.
- **Mood distribution** + **sentiment timeline** (powered by AI sentiment).
- **Media stats** — counts and storage.

---

## 21. Encryption

Protect sensitive items with **AES-256-GCM** encryption (passphrase-derived key, per-item salt).

- **Encrypt** an entry or note from its editor controls — set a passphrase.
- A **lock icon** shows it's encrypted; the body is ciphertext at rest.
- **Decrypt** by entering the same passphrase.
- You can also encrypt/decrypt just a **text selection**.

> ⚠️ **If you forget the passphrase, encrypted content cannot be recovered.** And never delete `<data-dir>/.secret_key` — it's required for decryption.

---

## 22. Export & Import

- **Export** your journal as **Markdown** (a ZIP of `.md` files), **HTML** (a styled single file), or **PDF** (requires WeasyPrint; desktop).
- **Import** from **CSV**, **Day One** (`.diary`/JSON), or **Markdown** archives.
- After importing, run **Deduplicate** to find/remove duplicate entries.

> Exports never include encrypted content in cleartext.

---

## 23. Backup & Cloud Sync

- **Local backup** — a full `.tar.gz` of database + media. Create/restore from Settings.
- **Scheduled backup** — automatic, DB-backed schedule (managed via APScheduler); runs catch-up on startup if missed.
- **Cloud providers** (OAuth, loopback callback on `127.0.0.1:18765`): **Google Drive, OneDrive, Dropbox, Box**. Credentials are stored encrypted.
- The web app's launcher prefers port **18765** so OAuth sign-in callbacks complete (it falls back to 8000-8019 if taken).

---

## 24. Google Calendar & Tasks Sync

Two-way sync with Google (mail stays on IMAP via the Email mode).

- Connect your Google account in **Settings → Google**.
- Toggle **Calendar** and/or **Tasks** sync independently.
- Trigger a full sync with **Sync all** (`POST /sync/all`); changes propagate both directions with provenance tracking.
- Requires the Google Calendar + Tasks scopes and a test user when first authorized.

---

## 25. Settings

Open from the sidebar (gear icon). Tabs:

| Tab | What you configure |
|---|---|
| **General** | Appearance (theme, font family/size), default template, other preferences. |
| **AI** | Ollama endpoint + model, pull the embedding model, AI feature toggles. |
| **Notes** | Notes-specific options. |
| **Email** | Email account setup. |
| **Google** | Google account connection, Calendar/Tasks sync toggles. |
| **Features** | Read-aloud voice/rate/volume/pitch, system-setup checks (Ollama, GStreamer, Tesseract). |
| **Data & Backup** | Storage location, import/export, backup schedule, cloud providers, reset. |
| **Dedication** | Memorial/dedication settings. |
| **About** | Version + credits. |

---

## 26. Keyboard Shortcuts

| Action | Shortcut |
|---|---|
| Global search palette | `Ctrl+K` |
| Screen snip (desktop, in Notes) | `Ctrl+Shift+S` |
| Save | `Ctrl+S` |
| Find & replace | `Ctrl+F` |
| Bold / Italic / Strikethrough | `Ctrl+B` / `Ctrl+I` / `Ctrl+U` |
| Inline code (in editor) | `Ctrl+K` |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Y` |
| Search palette: navigate/open/close | `↑` `↓` / `Enter` / `Esc` |
| Close overlay/modal | `Esc` |

---

## 27. Troubleshooting

**The app didn't change after I upgraded.**
The old process is still running. Fully quit it (web: `lifelogr --stop`; desktop: quit from the app menu) and relaunch.

**OCR says "install tesseract".**
Run `sudo apt install tesseract-ocr`, or **Settings → Features → System Setup**.

**Screen snip does nothing (desktop).**
Another app may have grabbed `Ctrl+Shift+S` — use the ✂️ toolbar button. On **Wayland**, approve the screen-capture portal prompt. (If you built the app yourself, ensure the `snip` Cargo feature was enabled and `libpipewire-0.3-dev` was present at build time.)

**AI tools hang or never return.**
You're likely using a "thinking" model on CPU. In **Settings → AI**, switch to a non-thinking model such as `gemma3:4b`.

**I can't see my journal in the other build (desktop vs web).**
The two builds use separate data directories by default. Relink via **Settings → Data & Backup → Storage location** (carry `.secret_key`).

**Voice recording doesn't work.**
Grant microphone permission; on Linux ensure GStreamer plugins are installed (`sudo apt install gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-plugins-bad`).

**Search isn't finding entries.**
Keyword search works offline; semantic/hybrid modes need the embedding model — pull `nomic-embed-text` in Settings → AI.

**Database errors.**
Back up first, then use **Settings → Data & Backup** to restore from a backup (or reset, as a last resort).

---

## 28. Data, Privacy & File Locations

Everything is stored locally under one data directory:

| Build | Default data directory |
|---|---|
| Desktop (Tauri) | `~/.local/share/com.lifelogr.desktop/` |
| Web | `~/.local/share/lifelogr/` |

Contents:
```
lifelogr.db       # your database (entries, notes, tasks, contacts, …)
.secret_key       # REQUIRED for encryption — never delete
media/            # uploaded images/audio/video
tts/              # read-aloud audio cache
backups/          # scheduled local backups
server.log        # web-app log (web build only)
```

**Privacy:** the backend binds to `127.0.0.1` only (no remote access, no auth — it's single-user). AI runs on-device via Ollama. Cloud backup/sync is **opt-in** and uses OAuth; credentials are stored encrypted. You can relocate the data directory at any time from Settings.
