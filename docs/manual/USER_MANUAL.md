# LifeLogr — User Manual

> **Local-first journaling for Linux (Ubuntu 24.04).**
> Your data stays on your machine. AI runs locally via Ollama by default; OCR via
> Tesseract; read-aloud via Edge TTS. Cloud AI and cloud backup are strictly opt-in.

*Version 0.10.1*

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Interface Overview](#2-interface-overview)
3. [Desktop vs Web — Which Build Are You In?](#3-desktop-vs-web--which-build-are-you-in)
4. [Journal Entries](#4-journal-entries)
5. [Notes Mode](#5-notes-mode)
6. [Clipping & OCR (Screen-Snip / Web-Clip)](#6-clipping--ocr-screen-snip--web-clip)
7. [Voice & Video Clips](#7-voice--video-clips)
8. [Templates](#8-templates)
9. [Tags](#9-tags)
10. [Markdown Reference](#10-markdown-reference)
11. [Search](#11-search)
12. [Calendar & Timeline Views](#12-calendar--timeline-views)
13. [Media & Attachments](#13-media--attachments)
14. [Read Aloud (TTS)](#14-read-aloud-tts)
15. [AI Writing Assistant](#15-ai-writing-assistant)
16. [Daily Writing Prompts](#16-daily-writing-prompts)
17. [Reminders](#17-reminders)
18. [Encryption](#18-encryption)
19. [Export & Import](#19-export--import)
20. [Backup & Cloud Sync](#20-backup--cloud-sync)
21. [Privacy & Data Egress](#21-privacy--data-egress)
22. [Settings](#22-settings)
23. [Scribble Pad & Zen Mode](#23-scribble-pad--zen-mode)
24. [Keyboard Shortcuts](#24-keyboard-shortcuts)
25. [Troubleshooting](#25-troubleshooting)
26. [Data, Privacy & File Locations](#26-data-privacy--file-locations)

---

## 1. Getting Started

### System requirements
- **Linux:** Ubuntu 24.04 LTS (or equivalent modern distro), Python 3.11+ (web build only), glibc.
- **Optional, for AI/OCR:** [Ollama](https://ollama.com) (text AI), Tesseract (OCR — auto-installed by the `.deb`).
- A working microphone (for voice clips) and speakers/headphones (for read-aloud).

### Install the desktop app (Tauri)
A native window with everything bundled. **Required if you want screen-snipping.**
```bash
sudo dpkg -i LifeLogr_0.10.1_amd64.deb
sudo apt-get install -f
```
Launch **LifeLogr** from your app menu.

### Install the web app (browser)
Lighter; the backend serves the app and you use it in a browser tab. The Python
virtualenv is built on your machine during install (needs network).
```bash
sudo dpkg -i lifelogr-web_0.10.1_amd64.deb
sudo apt-get install -f
```
Launch **LifeLogr** from your app menu (or run `lifelogr`). It opens a browser tab on
a free local port. Stop it with `lifelogr --stop`.

> **Upgrading:** fully **quit** the running app before relaunching (closing the window
> may leave the old process alive). Web app: `lifelogr --stop`.

### First launch
1. The sidebar lists the main areas: **Journal, Timeline, Notes, Reminders, Media**,
   plus **Search** and a **Scribble Pad** toggle.
2. Open **Journal** to write a dated entry, or **Notes** for standalone notebooks.
3. (Optional) Go to **Settings → AI** to enable AI features. By default LifeLogr uses
   local **Ollama** — set a CPU-friendly model like `gemma3:4b`. You can instead
   connect a cloud provider (see [§15](#15-ai-writing-assistant)).

---

## 2. Interface Overview

```
┌──────────┬──────────────────────────────────────┐
│ Sidebar  │   Active view (Journal / Notes /     │
│ (nav +   │   Reminders / Media …)               │
│  search) │   plus an editor panel on the right  │
│          │   for entries and notes              │
└──────────┴──────────────────────────────────────┘
```

- **Sidebar** — navigation between modes. You can reorder the nav items by dragging.
  At the bottom: theme toggle and **Settings**.
- **Search** — press `Ctrl+K` anywhere to open the global search palette.
- **Scribble Pad** — a slide-in quick-note panel (toggle from the sidebar) for fast,
  unfiled thoughts.
- **Editor panel** — when you open a journal entry or a note, it appears on the right
  with a title field, a markdown formatting toolbar (collapsible), the body, and a
  bottom action bar (tags, media, AI tools, read-aloud, save).
- **Zen mode** — press `Ctrl+.` to hide the chrome and focus on writing; press again
  to restore (see [§23](#23-scribble-pad--zen-mode)).

---

## 3. Desktop vs Web — Which Build Are You In?

| Capability | Desktop (Tauri) | Web (browser) |
|---|:---:|:---:|
| Screen-snippet (`Ctrl+Shift+S` / ✂️) | ✅ | ❌ |
| Web-clip text (🌐) | ✅ | ✅ |
| OCR | ✅ (auto after a snip) | endpoint exists; no in-app button¹ |
| Voice & video clips | ✅ | ✅ |
| All other features (AI, encryption, sync, etc.) | ✅ | ✅ |
| **Data directory** | `~/.local/share/com.lifelogr.desktop/` | `~/.local/share/lifelogr/` |

¹ The two builds use **separate databases** by default. To share one journal between
them, point one build at the other's data directory via **Settings → Data → Storage
location** (and copy the `.secret_key` so encrypted items still decrypt).

---

## 4. Journal Entries

Journal entries are **date-bound** (one per day, by default).

### Create an entry
- Click a day in the **Calendar**, or use the **new entry** action.
- A new entry for that date opens in the editor. If you've set a **default template**,
  its content is pre-filled.

### Entry fields
- **Title** — optional heading.
- **Date** — the entry's date.
- **Mood** — a short mood label.
- **Body** — markdown (see [§10](#10-markdown-reference)).
- **Summary** — a one-line summary (can be AI-generated; see [§15](#15-ai-writing-assistant)).
- **Tags** — assign tags (see [§9](#9-tags)).
- **Location** — optional latitude/longitude/place name.
- **Media** — attach images/audio/video/documents (see [§13](#13-media--attachments)).

### Saving
- Press **`Ctrl+S`** or click **Save**. A status indicator shows when a save is in
  progress/complete.
- Journal entries save on demand and on navigate. **Notes** use manual save
  (see [§5](#5-notes-mode)).

### Formatting toolbar
Bold, italic, strikethrough, inline code, code block, link, headings, bullet/numbered
lists, checklists, blockquote, alignment, tables, emoji, find & replace — plus **AI
tools** and (in Notes) the **clip** buttons. See [§24](#24-keyboard-shortcuts) for
shortcuts.

---

## 5. Notes Mode

Notes are standalone, non-date-bound documents organized into **folders**.

### Structure
- **Folders** — create them in the left tree; folders can be **nested** (sub-folders),
  and each can have a color.
- **Notes** — belong to a folder; can be **pinned** and **color-coded**.
- **Pages** — each note has tabbed pages (like sections). Add/rename/reorder/delete pages.
- **Tags** — type `#tags` right in the note body (see [§9](#9-tags)).

### The editor
- Full markdown editor (shared with journal entries): formatting toolbar, live
  preview, find & replace.
- **Manual save** — Notes do **not** autosave as you type. Click **Save** (or leave the
  note) to persist. *Switching to another note without saving discards the outgoing
  note's edits.*
- On opening **Notes**, a **fresh blank note** is created and opened automatically
  (ready to write or clip).

### Embedding media
- Drag-and-drop, paste, or use the embed (🖼️/🎵/🎬) buttons. In the desktop app you
  can also drop a file from your file manager (native path import).
- Embedded images are shown resizable in the preview.

### Encrypting a note
See [§18](#18-encryption).

### Searching notes
Notes are included in the global search palette (`Ctrl+K`) and have their own FTS5
search.

### Single-note Markdown import / export
- **Export** — the editor's **⬇ download** button saves the current note as a
  standalone `.md` file (YAML frontmatter + body).
- **Import** — the **Import Markdown** button in the notes toolbar loads a `.md` file
  as a new note (frontmatter-aware) and opens it.

---

## 6. Clipping & OCR (Screen-Snip / Web-Clip / Image Upload)

Capture content into an entry or note, embed it as a picture, and read its text with OCR.

### Screen snip (Notes, desktop app only)
1. Open a **non-encrypted note** in Notes mode.
2. Trigger a snip:
   - **`Ctrl+Shift+S`** (works from anywhere), or
   - the **✂️ scissors** button in the formatting toolbar.
3. The app hides itself, captures the screen, then shows the capture in a full-screen
   **crop overlay**. *(On Wayland, approve the screen-capture portal prompt the first
   time.)*
4. **Drag a rectangle** over the region you want and release.
5. The cropped image is **embedded into the note**, then **OCR runs automatically** and
   the recognized text is inserted beneath the image in a collapsible `📷 OCR` block —
   and becomes **searchable**.

> Browsers can't capture your screen, so the snip is **desktop-only**. If
> `Ctrl+Shift+S` does nothing, another app may have grabbed that key — use the ✂️
> toolbar button.

### Image uploads (Journal & Notes, both builds)
- Attach an image with the **📎 paperclip** button or **drag-and-drop** it onto the
  editor. The image is **embedded inline in the body** (not parked in a side panel),
  then **OCR runs automatically** and the recognized text is inserted beneath it in a
  `📷 OCR` block.
- Non-image files (audio, video, PDFs, …) are still stored as side-panel attachments.

### Web-clip (both builds)
- Click the **🌐 globe** button and enter a URL.
- LifeLogr fetches the page **server-side** and inserts its main text as markdown.
- The fetch is **SSRF-hardened** (internal/loopback addresses are blocked on every
  hop, including redirects).
- OCR applies to images you snip or upload, not to web-clipped text (it's already text).

### OCR requirements & language
- **Tesseract** must be installed (the `.deb` declares it as a dependency; if missing,
  OCR returns a helpful error with install instructions).
- The **OCR language** is configurable in **Settings → Appearance** — **English** or
  **Tamil**. Tamil needs the `tesseract-ocr-tam` data pack (the desktop `.deb` ships
  English; install Tamil separately if you use it). If the selected language's data
  isn't installed, OCR returns a clear error naming the missing pack.

---

## 7. Voice & Video Clips

- **Voice recording** — click the **microphone** in the editor's bottom bar. A timer
  shows while recording; click **Stop** to save the clip to the entry. Playback inline;
  delete unwanted clips.
- **Video notes** — attach short video clips to an entry (upload via the media/embed
  controls). They play inline like any embedded video.

> **Note:** LifeLogr records audio and stores it as an attachment. **Speech-to-text
> transcription is not included** in this release.

On Linux, recording needs GStreamer plugins (the desktop `.deb` depends on them).

---

## 8. Templates

Templates pre-fill new entries with structured markdown.

- **Built-in templates** ship with the app (e.g., daily reflection, gratitude) and
  can't be edited.
- **Custom templates** — create your own from the template picker (name + markdown body).
- **Apply** — when creating an entry, pick a template to pre-fill; for an existing
  entry, applying a template appends its content.
- **Default template** — set in **Settings → Appearance** so every new entry starts
  with that template.

---

## 9. Tags

**Tags live in your text.** Type a `#hashtag` anywhere in an entry or note body and it
becomes a tag — there's no separate tag panel to maintain. As you type `#`, an
**autocomplete** picker suggests your existing tags; pick one or keep typing to create a
new tag. Tags are extracted from the body on save, so adding, renaming, or removing a
`#tag` in the text is all it takes.

- **Assign** — just write `#tag` in the body, in either the Journal or Notes editor.
  Matching `#tokens` are turned into tags automatically.
- **Filter** — click tag pills to narrow the calendar/timeline and the search palette.
- **Manage** — rename or delete a tag from the tag tree; changes propagate to every
  entry/note that uses it.

> Tags are derived server-side from the `#tokens` in the body (`hashtag.py`), so the
> tag ids sent by the editor are ignored on save — edit the text to change tags.

---

## 10. Markdown Reference

LifeLogr renders **GitHub-Flavored Markdown** in the preview pane (sanitized via
DOMPurify).

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
- Embedded media (uploaded via the app) is inserted as `![name](/api/v1/.../file)` and
  rendered inline; audio/video get inline players.

---

## 11. Search

Press **`Ctrl+K`** to open the global search palette.

### Three modes
| Mode | What it does |
|---|---|
| **Keyword** (`Aa`) | Full-text search (SQLite FTS5, BM25-ranked) across titles and bodies. |
| **Semantic** (`AI`) | Meaning-based search using local embeddings (`nomic-embed-text`). Finds conceptually similar content without exact words. |
| **Hybrid** (`Mix`, default) | Combines keyword + semantic via Reciprocal Rank Fusion. |

### Scope & filters
- Results span **entries and notes** in one stream.
- Filter by **mood**, **tags**, and **date range**.
- Search history is remembered; navigate with `↑`/`↓`, open with `Enter`, close with
  `Esc`.
- The default mode is set in **Settings → Appearance → Search mode**.

> Semantic/hybrid modes need the embedding model. Pull it from **Settings → AI** or
> run `ollama pull nomic-embed-text`. If you've enabled a **cloud** AI provider,
> embeddings are generated through it (see [§21](#21-privacy--data-egress)).

---

## 12. Calendar & Timeline Views

- **Calendar (Journal)** — month grid; days with entries are marked. Click a day to
  open/create that day's entry. Filter by tag.
- **Timeline** — reverse-chronological list of entries with previews; click to open.

---

## 13. Media & Attachments

- **Supported:** images (JPG/PNG/GIF/WebP/BMP/TIFF), audio (MP3/WAV/OGG/M4A…), video
  (MP4/WebM/MOV), PDF, CSV, text. Max **25 MB** per file.
- **Attach** — drag-and-drop, paste, the embed buttons, or (desktop) drop a file from
  your file manager.
- **Gallery (Media mode)** — browse all media across entries; timeline view and
  global-search integration.
- Images are auto-compressed to WebP for storage; original quality is preserved where
  it matters for OCR.
- Inline images in notes are resizable in the preview.

---

## 14. Read Aloud (TTS)

- Select text (or open an entry/note) and choose **Read aloud**.
- Audio is generated and locally cached via **Microsoft Edge TTS** (`edge-tts`) and
  served with seek support.
- Configure **voice, rate, volume, and pitch** in **Settings → Appearance →
  Text-to-speech** (the setting persists; a preview button lets you test it).
- The TTS cache lives under `<data-dir>/tts/`.

---

## 15. AI Writing Assistant

AI assistance runs **locally by default via Ollama**. You can optionally connect a
cloud model (see below). Configure everything in **Settings → AI**.

### Provider: local Ollama (default, offline)
- Set the **Ollama URL**, click **Test connection**, then pick a **chat model** and an
  **embedding model** (e.g. `nomic-embed-text`).
- A non-thinking, CPU-friendly model like `gemma3:4b` is recommended. Avoid "thinking"
  models on CPU — they can hang.
- Pull new models from the tab, or refresh the model list.

### Provider: cloud (opt-in)
- Add any OpenAI-compatible provider: **OpenAI, Groq, OpenRouter, Kimi (Moonshot),
  Google Gemini**, or a **Custom** endpoint. Enter base URL, model, and API key.
- **API keys are AES-GCM encrypted at rest** and never returned by the API.
- **Activate** a provider to route AI through it. **Ollama stays the automatic
  fallback** if the active cloud provider is unreachable.
- When a cloud model is active, a warning banner appears in the AI tab and the
  **Privacy** tab reports it (see [§21](#21-privacy--data-egress)).

### On-demand tools (select text → AI / right-click menu)
- **Grammar**
- **Rewrite** (with style options), **Clarity**
- **Tone**, **Expand**, **Define**, **Voice** (active/passive)
- **Summarize**, **Key Points**, **Actions**
- **Shorten**, **Simplify**, **Polish**
- **Translate** (pick a language)
- **Structure**, **Title**

Each result can be **Replaced**, **Inserted**, or **Copied**.

### Automatic analysis (runs in the background after you save)
- **Summary** — a one-line summary (shown in timeline/search previews).
- **Sentiment** — primary/secondary emotion + valence.
- **Reflection prompts** — questions to reflect further (shown on the entry).
- **Tag suggestions** — suggested tags appear as pills; click to insert one as a `#tag`.
- **Themes** — recurring topics detected across your writing (Settings → AI → Themes
  & Insights).
- **Continue writing** — a writer's-block helper that suggests a continuation.

### Feature toggles
Enable/disable each AI feature individually in **Settings → AI → AI Features**
(embeddings, tag suggestions, sentiment, summarization, reflection prompts, writer's
block helper). If AI is unavailable, everything degrades gracefully — saving still
works.

---

## 16. Daily Writing Prompts

LifeLogr offers a **writing prompt of the day** to help you start when you're stuck.
Use it to seed a new entry or a scribble. The prompt rotates daily.

---

## 17. Reminders

- Create time-based reminders (title, optional message, time, days of the week).
- **Enable/disable**, edit, **test** (preview the notification), or delete.
- Reminders fire while the app is running and show a desktop notification; clicking it
  focuses LifeLogr.
- Reminders that came due while the app was closed are caught up on next launch.

---

## 18. Encryption

Protect sensitive items with **AES-256-GCM** encryption (passphrase-derived key via a
memory-hard **scrypt** KDF, per-item salt).

- **Encrypt** an entry or note from its editor controls — set a passphrase.
- A **lock icon** shows it's encrypted; the body is ciphertext at rest.
- **Decrypt** by entering the same passphrase.
- You can also encrypt/decrypt just a **text selection**.

> ⚠️ **If you forget the passphrase, encrypted content cannot be recovered.** And never
> delete `<data-dir>/.secret_key` — it's required for decryption.

---

## 19. Export & Import

- **Export** your journal as **Markdown** (a ZIP of `.md` files, Obsidian-compatible),
  **HTML** (a styled single file), **PDF** (desktop — bundled fpdf2), **Diarium
  JSON**, or a **Diarium `.diary` SQLite** database.
- **Import** from **CSV**, **Diarium** (`.diary`/JSON), or **Markdown/ZIP** archives.
- After importing, run **Deduplicate** (Settings → Data → Maintenance) to find/remove
  duplicate entries.

> Exports never include encrypted content in cleartext.

---

## 20. Backup & Cloud Sync

Configure in **Settings → Backup**.

### Local backup
- A full `.tar.gz` of database + media. **Download** to keep a copy, or **Import** to
  restore. Restore is path-traversal-safe (PEP 706 tar filtering) and atomic.

### Scheduled backup
- Automatic, **DB-backed** schedule (managed via APScheduler). Set a cron expression;
  runs **catch-up on startup** if a run was missed while the app was down.

### Cloud providers
OAuth sign-in (loopback callback on `127.0.0.1:18765`, so the callback completes
locally): **Google Drive, OneDrive, Dropbox, Box**. Also supported via manual config:
**WebDAV** and **Synology NAS** (a WebDAV preset).
- Cloud **credentials/tokens are encrypted at rest** and auto-refreshed.
- **Run now** performs an incremental backup; **Snapshots** lists history; **Restore**
  pulls the latest cloud backup.

> The web app's launcher prefers port **18765** so OAuth sign-in callbacks complete
> (it falls back to 8000-8019 if taken).

---

## 21. Privacy & Data Egress

Open **Settings → Privacy** for a live **egress report** — a per-surface table that
states plainly what leaves your device:

| Surface | Leaves device? |
|---|---|
| **AI tools & analysis** | Only if a **cloud** provider is active (Ollama = stays local) |
| **Embeddings** (semantic search) | Same as AI tools |
| **Cloud backup** | Yes — only the providers you've configured |
| **Web-clip** | Only the **URL** you enter; your journal content stays local |
| **OCR** | No — local Tesseract |

No content ever leaves your machine unless *you* turned on a cloud AI provider or a
cloud backup provider. The default is fully local.

---

## 22. Settings

Open from the sidebar (gear icon). Tabs:

| Tab | What you configure |
|---|---|
| **Appearance** | Theme (dark mode), font family/size, auto-save interval, OCR language, default title, default template, **search mode**, **read-aloud** voice/rate/volume/pitch, and a keyboard-shortcut reference. |
| **AI** | Provider management (add/activate/test cloud providers, or configure local Ollama), chat & embedding model selection, model pulling/refresh, AI feature toggles, Themes & Insights. |
| **Data** | Storage location & stats, import/export, maintenance (deduplicate, vacuum, integrity check), diagnostics (health, rebuild search index). |
| **Backup** | Local backup download/restore, scheduled backup, and cloud providers (Google Drive, OneDrive, Dropbox, Box, WebDAV, Synology NAS). |
| **Privacy** | Live data-egress report across all surfaces. |
| **Dedication** | Memorial/dedication tribute (a full-bleed tribute shown in About; optional background audio). |
| **About** | Version + credits, feature badges, GitHub/license links, update check, release notes (the embedded changelog), and (desktop) **System Setup** to install Ollama/GStreamer. The **Danger Zone** resets the database (requires typing `RESET`). |

---

## 23. Scribble Pad & Zen Mode

- **Scribble Pad** — toggle a slide-in panel from the sidebar for quick, unfiled notes.
  Great for capturing a thought without leaving what you're doing.
- **Zen mode** — press **`Ctrl+.`** to hide the sidebar and chrome for distraction-free
  writing; press `Ctrl+.` (or `Esc`) again to restore.

---

## 24. Keyboard Shortcuts

| Action | Shortcut |
|---|---|
| Global search palette | `Ctrl+K` |
| Screen snip (desktop, in Notes) | `Ctrl+Shift+S` |
| Save | `Ctrl+S` |
| Find & replace | `Ctrl+F` |
| Zen mode (distraction-free) | `Ctrl+.` |
| Bold / Italic / Strikethrough | `Ctrl+B` / `Ctrl+I` / `Ctrl+Shift+X` |
| Clear formatting | `Ctrl+\` |
| Inline code (in editor) | <code>Ctrl+E</code> |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Search palette: navigate/open/close | `↑` `↓` / `Enter` / `Esc` |
| Close overlay/modal | `Esc` |

The full list is also shown in **Settings → Appearance**.

---

## 25. Troubleshooting

**The app didn't change after I upgraded.**
The old process is still running. Fully quit it (web: `lifelogr --stop`; desktop: quit
from the app menu) and relaunch.

**OCR says "install tesseract".**
Run `sudo apt install tesseract-ocr`, or on desktop use **Settings → About → System
Setup**.

**Screen snip does nothing (desktop).**
Another app may have grabbed `Ctrl+Shift+S` — use the ✂️ toolbar button. On
**Wayland**, approve the screen-capture portal prompt. (If you built the app yourself,
ensure the `snip` Cargo feature was enabled and `libpipewire-0.3-dev` was present at
build time.)

**AI tools hang or never return.**
You're likely using a "thinking" model on CPU. In **Settings → AI**, switch to a
non-thinking model such as `gemma3:4b`. (Or activate a cloud provider.)

**I can't see my journal in the other build (desktop vs web).**
The two builds use separate data directories by default. Relink via **Settings → Data
→ Storage location** (carry `.secret_key`).

**Voice/video recording doesn't work.**
Grant microphone permission; on Linux ensure GStreamer plugins are installed
(`sudo apt install gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav gstreamer1.0-plugins-bad`).

**Search isn't finding entries.**
Keyword search works offline; semantic/hybrid modes need the embedding model — pull
`nomic-embed-text` in Settings → AI. If results look stale, rebuild the index from
**Settings → Data → Diagnostics → Rebuild search index**.

**Database errors.**
Back up first, then use **Settings → Backup** (or Data → Maintenance) to restore from a
backup, vacuum, run an integrity check, or — as a last resort — reset.

---

## 26. Data, Privacy & File Locations

Everything is stored locally under one data directory:

| Build | Default data directory |
|---|---|
| Desktop (Tauri) | `~/.local/share/com.lifelogr.desktop/` |
| Web | `~/.local/share/lifelogr/` |

Contents:
```
lifelogr.db       # your database (entries, notes, reminders, …)
lifelogr.db.boot-bak-* # rotating boot snapshots — auto-restored if the DB corrupts
.secret_key       # REQUIRED for encryption — never delete
media/            # uploaded images/audio/video
tts/              # read-aloud audio cache
backups/          # scheduled local backups
server.log        # web-app log (web build only)
```

**Privacy:** the backend binds to `127.0.0.1` only (no remote access, no auth — it's
single-user). AI runs on-device via Ollama by default; OCR runs locally via Tesseract.
Cloud AI and cloud backup are **opt-in** and use OAuth; credentials/tokens are stored
encrypted. You can relocate the data directory at any time from **Settings → Data →
Storage location**.
