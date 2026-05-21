# Diarilinux — User Manual

> Privacy-first, offline-first daily journaling for Linux, Windows, macOS, Android, and iOS.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Interface Overview](#2-interface-overview)
3. [Creating & Editing Entries](#3-creating--editing-entries)
4. [Templates](#4-templates)
5. [Tags](#5-tags)
6. [Markdown Guide](#6-markdown-guide)
7. [Search](#7-search)
8. [Calendar View](#8-calendar-view)
9. [Timeline View](#9-timeline-view)
10. [Media & Attachments](#10-media--attachments)
11. [Voice Recording & Transcription](#11-voice-recording--transcription)
12. [AI Writing Assistant](#12-ai-writing-assistant)
13. [Geotagging & Map View](#13-geotagging--map-view)
14. [Analytics](#14-analytics)
15. [Reminders](#15-reminders)
16. [Version History](#16-version-history)
17. [Encryption](#17-encryption)
18. [Export & Import](#18-export--import)
19. [Backup & Sync](#19-backup--sync)
20. [Settings](#20-settings)
21. [Keyboard Shortcuts](#21-keyboard-shortcuts)
22. [Plugins](#22-plugins)
23. [Troubleshooting](#23-troubleshooting)

---

## 1. Getting Started

### System Requirements

| Platform | Requirements |
|----------|-------------|
| Linux | Ubuntu 20.04+ or equivalent, glibc 2.31+ |
| Windows | Windows 10/11 (x64) |
| macOS | macOS 12 Monterey+ |
| Android | Android 10+ |
| iOS | iOS 16+ |

### Installation

#### Desktop (Linux/Windows/macOS)

**Option A — Run from source (developers)**
```bash
# Clone the repository
git clone https://github.com/your-org/diarilinux.git
cd diarilinux

# Launch both frontend and backend
chmod +x dev.sh
./dev.sh
```

The `dev.sh` script automatically finds available ports and starts both the FastAPI backend and Vite frontend. Press `Ctrl+C` to stop both servers.

**Option B — Pre-built package**
- **Linux**: Download the `.AppImage` or `.deb` file from releases. AppImages run without installation. DEB packages install via `sudo dpkg -i diarilinux_*.deb`.
- **Windows**: Download the `.msi` installer and run it.
- **macOS**: Download the `.dmg` file, drag to Applications.

**Option C — Docker**
```bash
docker compose up -d
# Access at http://localhost:8000
```

#### Mobile (Android/iOS)

- **Android**: Download the `.apk` from releases and install, or get it from Google Play.
- **iOS**: Install from the App Store or use TestFlight for beta builds.

### First Launch

When you first open Diarilinux:

1. The **calendar view** loads showing the current month
2. A **new entry** is automatically opened in the right panel
3. The **sidebar** on the left provides navigation to all features
4. Start writing — your entry is saved automatically as you type

---

## 2. Interface Overview

Diarilinux uses a three-panel layout:

```
┌──────────┬──────────────────┬─────────────────────┐
│          │                  │                     │
│ Sidebar  │   Content Area   │    Editor Panel     │
│ (nav)    │  (calendar,      │  (entry editor +    │
│          │   timeline,      │   preview)          │
│          │   analytics)     │                     │
│          │                  │                     │
└──────────┴──────────────────┴─────────────────────┘
```

### Sidebar

The sidebar provides navigation to all major views:

| Icon | View | Description |
|------|------|-------------|
| Calendar | **Calendar** | Monthly view with entry indicators |
| List | **Timeline** | Chronological list of all entries |
| Search | **Search** | Opens global search palette |
| Bar Chart | **Analytics** | Writing statistics and insights |
| Book | **Digest** | AI-generated weekly summary of your journaling |
| Map | **Map** | Geotagged entries on a map |
| Bell | **Reminders** | Manage journaling reminders |
| Sunrise | **On This Day** | AI reflection on entries from past years |
| Settings | **Settings** | App preferences and data management |

**Sidebar controls:**
- Click the hamburger icon at the top to collapse/expand
- The **new entry** (+) button creates a blank entry
- The **theme toggle** (sun/moon) at the bottom switches dark/light mode
- Sidebar auto-collapses on screens narrower than 768px

### Editor Panel

The right panel contains the entry editor with:
- **Title field** — set the entry title
- **Date field** — change the entry date
- **Formatting toolbar** — markdown formatting buttons
- **Body editor** — the main writing area
- **Bottom bar** — word count, template picker, tag manager, media, recording, geotag, AI tools, and save controls

---

## 3. Creating & Editing Entries

### Creating a New Entry

1. Click the **+** button in the sidebar, or
2. Click on any **date** in the calendar view, or
3. Press the new entry keyboard shortcut

A new entry is created with today's date (or the selected calendar date). If you have a **default template** set, its content is automatically inserted.

### Editing an Entry

1. Click any entry in the calendar, timeline, or search results
2. The entry opens in the editor panel on the right
3. Start editing — changes are **auto-saved** after 2 seconds of inactivity
4. The save indicator shows when changes are pending

### Editor Toolbar

The formatting toolbar provides these controls:

| Button | Shortcut | Action |
|--------|----------|--------|
| **B** | `Ctrl+B` | Bold text |
| *I* | `Ctrl+I` | Italic text |
| ~~S~~ | `Ctrl+U` | Strikethrough |
| `Code` | `Ctrl+K` | Inline code |
| Code block | — | Multi-line code block |
| Link | — | Insert hyperlink |
| Image | — | Insert image |
| Find | `Ctrl+F` | Find & replace |
| H1 / H2 | — | Headings |
| List | — | Bullet list |
| 1. List | — | Numbered list |
| Quote | — | Blockquote |
| Checkbox | — | Task checkbox |
| Table | — | Insert table |
| Line | — | Horizontal rule |
| Undo | `Ctrl+Z` | Undo last action |
| Redo | `Ctrl+Y` | Redo last action |

### Word Statistics

The bottom of the editor shows real-time stats:
- **Words** — total word count
- **Characters** — character count
- **Lines** — line count
- **Paragraphs** — paragraph count
- **Reading time** — estimated reading time

### Preview Mode

Toggle between edit and preview mode to see how your markdown renders. The preview supports:
- Full GitHub Flavored Markdown (GFM)
- Tables, task lists, strikethrough
- Line breaks rendered as `<br>`
- Syntax-highlighted code blocks

### Switching Entries

If you have unsaved changes and try to switch to another entry, Diarilinux shows a **save prompt** with three options:
- **Save** — save current changes, then switch
- **Discard** — discard changes, then switch
- **Cancel** — stay on the current entry

---

## 4. Templates

Templates let you pre-fill new entries with structured content.

### Built-in Templates

Diarilinux includes four built-in templates:

| Template | Structure |
|----------|-----------|
| **Daily Reflection** | How I'm feeling / What I did today / Grateful for |
| **Gratitude Journal** | Three things I'm grateful for / Why |
| **Travel Log** | Location / Highlights / Photos & Memories |
| **Weekly Review** | Wins this week / Challenges / Goals for next week |

Built-in templates cannot be edited or deleted.

### Creating a Custom Template

1. Open any entry in the editor
2. Click the **template button** (grid/layout icon) in the bottom toolbar
3. In the template picker, click **"Create Template"**
4. Enter a **name** and **body** (markdown supported)
5. Click **Save**

### Applying a Template

- **New entry**: Click the template button, select a template — the template body fills the editor
- **Existing entry**: Click the template button, select a template — content is appended to the current body

### Setting a Default Template

1. Go to **Settings** (gear icon in sidebar)
2. Under **Preferences**, find the **Default Template** dropdown
3. Select a template — all new entries will start with this template's content

### Managing Templates

- **Edit**: Click the pencil icon on any custom template in the picker
- **Delete**: Click the trash icon on any custom template
- Built-in templates show a **lock icon** and cannot be modified

---

## 5. Tags

Tags organize and categorize your entries.

### Creating Tags

1. In the editor, click the **tag button** (tag icon) in the bottom toolbar
2. Type a tag name in the search field
3. Click **"Create: tagname"** to create a new tag
4. Click tags to toggle them on/off for the current entry

### Hierarchical Tags

Tags support parent-child relationships:
- Create a parent tag first (e.g., "Travel")
- When creating a child tag, select the parent from the dropdown
- Child tags appear nested under their parent

### Filtering by Tags

- In the **calendar view**, use the tag filter dropdown to show only entries with specific tags
- In the **search palette**, click tag pills to narrow search results
- Tag pills show the count of entries using each tag

### Managing Tags

- Navigate to the tag management view through settings or the tag panel
- **Rename** a tag to update it across all entries
- **Delete** a tag to remove it from all entries
- Tag counts update automatically

---

## 6. Markdown Guide

Diarilinux supports full **GitHub Flavored Markdown (GFM)**.

### Basic Formatting

```markdown
**Bold text**
*Italic text*
~~Strikethrough~~
`Inline code`
```

### Headings

```markdown
# Heading 1
## Heading 2
### Heading 3
```

### Lists

```markdown
- Bullet item
- Another item

1. Numbered item
2. Second item
```

### Task Lists

```markdown
- [x] Completed task
- [ ] Pending task
```

### Links and Images

```markdown
[Link text](https://example.com)
![Image alt](image-url.jpg)
```

### Blockquotes

```markdown
> This is a quote
> Multiple lines
```

### Code Blocks

````markdown
```python
def hello():
    print("Hello, World!")
```
````

### Tables

```markdown
| Column 1 | Column 2 |
|----------|----------|
| Cell 1   | Cell 2   |
```

### Horizontal Rule

```markdown
---
```

### Line Breaks

Press `Enter` twice for a new paragraph, or end a line with two spaces for a soft line break.

---

## 7. Search

### Global Search Palette

Press **`Ctrl+K`** from anywhere in the app to open the search palette.

```
┌─────────────────────────────────────────┐
│  🔍 Search entries...    [Aa][AI][Mix]  │
│                                         │
│  #travel #nature #work ...              │
│                                         │
│  📅 2026-05-19  My morning routine...   │
│  📅 2026-05-18  Today I visited...      │
│  📅 2026-05-15  Reflections on...       │
│                                         │
│  3 results  ↑↓ Navigate  Enter Open     │
└─────────────────────────────────────────┘
```

### Search Modes

The search palette supports three modes, toggled via the segmented control at the top-right:

| Mode | Label | Description |
|------|-------|-------------|
| **Keyword** | `Aa` | Traditional full-text search with exact text matching (BM25) |
| **Semantic** | `AI` | AI-powered meaning-based search using embeddings — finds conceptually similar content even without exact word matches |
| **Hybrid** | `Mix` | Combines keyword and semantic results using Reciprocal Rank Fusion (default, recommended) |

> Semantic and hybrid modes require the `nomic-embed-text` embedding model. Pull it from Settings → AI Features, or run `ollama pull nomic-embed-text`.

### Search Features

- **Full-text search** — searches entry titles and body content
- **Semantic search** — finds entries by meaning, not just keywords
- **Live results** — results update as you type (with debounce)
- **Highlighted snippets** — matching text is highlighted with `<mark>` tags
- **Tag filtering** — click tag pills below the search box to narrow results
- **Keyboard navigation** — use `↑`/`↓` arrows to navigate, `Enter` to open, `Esc` to close

### Search Controls

| Key | Action |
|-----|--------|
| `Ctrl+K` | Open/close search palette |
| `↑` / `↓` | Navigate results |
| `Enter` | Open selected entry |
| `Esc` | Close search palette |
| Click tag pill | Filter by tag |

---

## 8. Calendar View

The calendar shows your entries organized by month.

### Calendar Features

- **Month navigation** — Previous/Next buttons to browse months
- **Today button** — Jump back to the current month
- **Entry dots** — Small dots appear on days that have entries
- **Click a day** — Opens the entry for that date (or creates a new one)
- **Tag filtering** — Filter calendar to show entries with specific tags

### Calendar Layout

```
┌───────────────────────────────────┐
│  ◀  May 2026            Today ▶   │
├─────┬─────┬─────┬─────┬─────┬─────┬─────┤
│ Sun │ Mon │ Tue │ Wed │ Thu │ Fri │ Sat │
├─────┼─────┼─────┼─────┼─────┼─────┼─────┤
│     │     │     │  1  │  2  │  3  │  4  │
│  5  │  6  │  7  │  8  │  9  │ 10  │ 11  │
│ 12  │ 13  │ 14  │ 15● │ 16  │ 17  │ 18● │
│ 19● │ 20  │ 21  │ 22  │ 23  │ 24  │ 25  │
│ 26  │ 27  │ 28  │ 29  │ 30  │ 31  │     │
└─────┴─────┴─────┴─────┴─────┴─────┴─────┘
```

Days with entries are marked with a dot (●). The current day is highlighted.

---

## 9. Timeline View

The timeline shows all entries in reverse chronological order.

### Timeline Features

- **Scrollable list** — entries grouped by date
- **Entry previews** — shows title and first few lines of body
- **Tag indicators** — colored dots show tags on each entry
- **Pagination** — loads 20 entries at a time with a "Load more" button
- **Click to edit** — clicking an entry opens it in the editor

---

## 10. Media & Attachments

### Supported File Types

| Category | Formats |
|----------|---------|
| Images | JPG, PNG, GIF, WebP |
| Videos | MP4, WebM, MOV |
| Audio | MP3, WAV, OGG, WebM |
| Documents | PDF, TXT, MD, JSON, CSV |

**Maximum file size:** 25 MB per file

### Uploading Media

1. Open an entry in the editor
2. Click the **paperclip/attachment** button in the bottom toolbar
3. Choose a file from your device — or **drag and drop** files directly
4. Add an optional caption
5. The file uploads and appears in the attachment panel

### Managing Attachments

- **View** — click an attachment to view it full-screen
- **Caption** — add or edit captions for your files
- **Delete** — click the trash icon to remove an attachment
- **Count** — the attachment button shows the count of media files

### Inline Images

When uploading images, they can be displayed inline in the entry body or as a gallery in the attachment panel.

---

## 11. Voice Recording & Transcription

### Recording Audio

1. Open an entry in the editor
2. Click the **microphone button** in the bottom toolbar
3. Grant microphone permission if prompted
4. A recording timer appears — speak your entry
5. Click **Stop** to end the recording
6. The audio file is saved and attached to the entry

### Transcribing Recordings

After recording (or uploading an audio file):

1. Click the **transcribe button** on the recording
2. The audio is processed using local Whisper transcription
3. Once complete, the transcription text is inserted into the entry body
4. Transcription status is shown on each recording

### Managing Recordings

- **Playback** — click play to listen to recordings inline
- **Duration** — recording length is displayed
- **Transcription status** — shows if a recording has been transcribed
- **Delete** — remove unwanted recordings

> **Note:** Voice transcription requires the Whisper model to be available. This is a desktop-only feature.

---

## 12. AI Writing Assistant

Diarilinux integrates with **Ollama** for local AI-powered writing assistance and intelligence features. All processing happens on your machine — no data is sent to external servers.

### Prerequisites

1. Install [Ollama](https://ollama.ai) on your system
2. Pull the main model: `ollama pull llama3.2:3b`
3. Pull the embedding model (for semantic search & analysis): `ollama pull nomic-embed-text`
4. Start Ollama: `ollama serve`

### On-Demand AI Features

#### Grammar Check
1. Select text in the editor
2. Click the **AI button** → **Grammar Check**
3. Review suggestions and apply corrections

#### Spell Check
1. Click **AI** → **Spell Check**
2. Spelling errors are highlighted with corrections
3. Apply individual or all corrections

#### Rewrite
1. Select text and click **AI** → **Rewrite**
2. Choose a style (formal, casual, concise, etc.)
3. Review the rewritten text and apply if desired

#### Auto-Tag Suggestions
After saving an entry, AI analyzes the content and suggests relevant tags. Suggestions appear as clickable pills below the tag dropdown — click to add, ignore to dismiss. The AI considers your existing tag names and reuses them where appropriate.

#### Writer's Block Helper
Stuck writing? Click the **lightbulb button** in the editor toolbar. The AI generates a 1-3 sentence continuation of your current text, shown as ghost text. Accept it to insert, or dismiss to try again.

#### AI Status
- The AI button shows connection status
- Green = Ollama connected and model loaded
- Red = Ollama unavailable — check if the service is running

### Automatic AI Analysis (Enrichment Pipeline)

Every time you save an entry, Diarilinux runs AI analysis in the background. This is non-blocking — your save completes instantly, and analysis runs afterward.

#### Sentiment Analysis
Each entry is analyzed for emotional content:
- **Primary emotion** — the dominant feeling (happy, anxious, grateful, etc.)
- **Secondary emotion** — a secondary feeling
- **Intensity** — emotional strength on a scale of 1-10
- **Valence** — positive/negative score from -1.0 to 1.0

Sentiment data powers the **Mood Timeline** chart in Analytics and the **Weekly Digest** emotional trajectory.

#### Auto-Summaries
The AI generates a concise one-line summary of each entry. This summary appears in:
- **Timeline view** — as preview text
- **Search results** — alongside the snippet
- **Weekly Digest** — used as input for the weekly narrative
- **Similar entries** — helps identify related content

#### Reflection Prompts
Each entry receives 3 AI-generated reflection prompts — questions designed to encourage deeper thinking about your experiences. Find them in the **"Reflect Further"** section when viewing an entry.

### Semantic Search & Similar Entries

#### How It Works
When you save an entry, the AI generates a 768-dimensional vector embedding using `nomic-embed-text`. These embeddings capture the *meaning* of your text, enabling:
- **Semantic search** — find entries by concept, not just keywords
- **Similar entries** — discover related entries across your entire journal

#### Finding Similar Entries
When viewing an entry, scroll to the **"Related Entries"** section at the bottom. This shows the most similar entries from your journal with similarity scores. Click any to navigate.

### Weekly Digest

The **Digest** view (book icon in sidebar) provides AI-generated weekly summaries of your journaling.

#### What's in a Digest
- **Themes** — key topics and subjects from the week, shown as tag pills
- **Emotional Trajectory** — a narrative of how your mood shifted through the week
- **Notable Moments** — highlighted events and experiences
- **Summary** — a warm, coherent narrative covering the week

#### Generating a Digest
- Digests are **auto-generated weekly** (Sunday at 2 AM via the scheduler)
- You can also click **"Generate Now"** to create one on demand
- Past digests are listed below the latest one

> Digests use a map-reduce approach: each entry's AI summary is combined and sent to the LLM for a coherent weekly narrative.

### On This Day

Navigate to **On This Day** in the sidebar (sunrise icon) to see entries from today's date in past years. The AI generates a reflection on your personal growth and how things have changed.

### Recurring Themes

The **Analytics** view includes a **Recurring Themes** section that uses AI to detect patterns across your journaling over time — career growth, health, relationships, creativity, and more. Each theme shows:
- **Frequency** — how many entries touch on this theme
- **Active months** — when it appeared
- **Description** — what the theme encompasses

### Feature Toggles

All AI features can be individually enabled or disabled from **Settings → AI Features**:

| Toggle | What it controls |
|--------|-----------------|
| Embeddings | Semantic search and similar entries |
| Tag Suggestions | Auto-tag suggestions on save |
| Sentiment Analysis | Mood detection and mood timeline |
| Summarization | Auto-summaries for entries |
| Reflection Prompts | AI-generated reflection questions |
| Writer's Block Helper | Continuation suggestions in editor |

> **Note:** AI features require Ollama to be running locally. If Ollama is unavailable, all features gracefully degrade — your entries save normally, and analysis is skipped.

---

## 13. Geotagging & Map View

### Adding a Location

1. Open an entry in the editor
2. Click the **location/pin button** in the bottom toolbar
3. In the geotag modal:
   - Click **"Use my location"** to auto-detect via GPS
   - Or manually enter latitude and longitude
   - The location name is auto-filled via reverse geocoding
4. Click **Save**

### Map View

Navigate to **Map** in the sidebar to see all geotagged entries:

- Entries are listed with their location names
- Click an entry to open it
- Nearby entries can be searched by location

### Removing a Location

Open the geotag modal and click **"Remove location"**.

---

## 14. Analytics

The analytics dashboard provides insights into your journaling habits.

### Overview Statistics

| Metric | Description |
|--------|-------------|
| Total entries | Count of all journal entries |
| Total words | Cumulative word count |
| Total media | Count of attached files |
| Total recordings | Count of voice recordings |
| Longest streak | Most consecutive days with entries |
| Current streak | Current consecutive writing days |
| Date range | Earliest to latest entry date |

### Writing Habits

- **Day-of-week chart** — bar chart showing which days you write most
- **Heatmap** — GitHub-style contribution heatmap for the year
  - Navigate between years
  - Each cell represents a day; darker = more entries

### Word Statistics

- Average words per entry
- Longest entry (word count)
- Shortest entry (word count)

### Tag Statistics

- Usage count for each tag
- Most-used tags ranked

### Media Statistics

- Total images, videos, and recordings
- Total storage space used

### Mood Timeline

A line chart showing your emotional valence over time (powered by AI sentiment analysis). Each data point represents an entry, with the Y-axis showing valence (-1.0 negative to 1.0 positive) and points colored by primary emotion.

> Requires AI sentiment analysis to be enabled. Only entries that have been analyzed by the AI enrichment pipeline appear on the chart.

### Recurring Themes

AI-detected patterns across your journaling. Shows themes that appear across multiple months with frequency counts and descriptions. See [Section 12 — Recurring Themes](#12-ai-writing-assistant) for details.

---

## 15. Reminders

### Creating a Reminder

1. Navigate to **Reminders** in the sidebar
2. Click **"Add Reminder"**
3. Fill in the details:
   - **Title** — reminder name (e.g., "Evening journal")
   - **Message** — optional text to show with the notification
   - **Time** — when to trigger (24-hour format)
   - **Days** — which days of the week (Mon=0 to Sun=6)
4. Click **Save**

### Managing Reminders

- **Toggle** — enable/disable a reminder without deleting it
- **Edit** — modify time, days, or message
- **Test** — click the test button to preview the notification
- **Delete** — permanently remove a reminder

### Notification Behavior

When a reminder triggers:
- A system notification appears with the title and message
- Clicking the notification opens Diarilinux
- Reminders only fire while the app is running

---

## 16. Version History

Diarilinux automatically saves revision snapshots of your entries.

### Viewing History

1. Open an entry
2. Access the revision history (through entry details or settings)
3. A list of all revisions is shown with timestamps and reasons

### Comparing Versions

- Select two revisions to see a **diff** comparison
- Changes in title and body are highlighted
- Additions shown in green, deletions in red

### Restoring a Version

1. Navigate to the revision you want to restore
2. Click **"Restore"**
3. The entry is updated to match that revision
4. A new revision snapshot is created (the restore is reversible)

---

## 17. Encryption

Encrypt individual entries to protect sensitive content.

### Encrypting an Entry

1. Open the entry
2. Access the encryption option (through entry controls)
3. Enter a **passphrase** — this is required to decrypt later
4. Click **Encrypt**
5. The entry body is encrypted using AES-256-GCM
6. A **lock icon** appears indicating the entry is encrypted

### Decrypting an Entry

1. Open the encrypted entry
2. Enter the **passphrase** you used to encrypt
3. Click **Decrypt**
4. The content is revealed

> **Important:** If you forget your passphrase, encrypted content **cannot be recovered**. Store passphrases securely.

---

## 18. Export & Import

### Exporting Entries

#### Markdown Export
1. Go to **Settings** → **Export**
2. Click **"Export Markdown"**
3. A ZIP file downloads containing all entries as markdown files

#### HTML Export
1. Go to **Settings** → **Export**
2. Optionally set a date range
3. Click **"Export HTML"**
4. A single styled HTML file downloads

#### PDF Export
1. Go to **Settings** → **Export**
2. Optionally set a date range
3. Click **"Export PDF"**
4. A PDF document downloads

> **Note:** PDF export requires WeasyPrint — desktop-only feature.

### Importing Entries

#### From File
1. Go to **Settings** → **Import**
2. Supported formats:
   - **Diarium** `.diary` files
   - **JSON** arrays of entries
   - **Markdown** ZIP archives
3. Select the file and click **Import**
4. A summary shows imported and skipped (duplicate) entries

#### From Backup
1. Go to **Settings** → **Backup & Restore**
2. Select a `.tar.gz` backup file
3. Click **Restore**

### Deduplication

After importing, run **"Deduplicate"** from Settings to find and remove duplicate entries. A summary shows how many duplicates were removed.

---

## 19. Backup & Sync

### Local Backup

1. Go to **Settings** → **Backup**
2. Click **"Export Backup"** to download a `.tar.gz` of your database and media
3. Click **"Import Backup"** to restore from a previous backup

### Cloud Backup

Diarilinux supports multiple cloud storage providers:

| Provider | Protocol |
|----------|----------|
| WebDAV | HTTP-based (Nextcloud, ownCloud, etc.) |
| Google Drive | OAuth2 |
| OneDrive | OAuth2 |
| Dropbox | OAuth2 |
| NAS | WebDAV or SMB |

#### Setting Up Cloud Backup

1. Go to **Settings** → **Cloud Backup**
2. Click **"Add Provider"**
3. Select your provider
4. Enter credentials
5. Click **"Test Connection"** to verify
6. Save the configuration

#### Scheduled Backups

1. After configuring a provider, set up a schedule
2. Enter a **cron expression** (e.g., `0 2 * * *` for 2 AM daily)
3. Backups run automatically at the specified times
4. Check status in the backup dashboard

### Sync

The sync system tracks local changes and pushes/pulls them to your cloud storage:

- **Push** — upload local changes to the cloud
- **Pull** — download remote changes to local
- **Queue** — view pending sync operations
- **Status** — see last sync time and pending count

---

## 20. Settings

Access settings via the **gear icon** in the sidebar.

### Appearance

| Setting | Options | Description |
|---------|---------|-------------|
| Theme | Dark / Light | Toggle between dark and light themes |
| Font Family | System, Segoe UI, Inter, Roboto, Lora, Merriweather, JetBrains Mono, Monospace | Change the editor font |
| Font Size | 12px – 24px | Adjust text size |
| Sidebar | Collapsed / Expanded | Toggle sidebar visibility |

### Preferences

| Setting | Description |
|---------|-------------|
| Default Template | Template applied to all new entries |
| Auto-geotag | Automatically detect location for new entries |
| TTS Voice | Voice used for text-to-speech |

### AI Features

| Setting | Description |
|---------|-------------|
| Embeddings | Enable/disable semantic search and similar entries |
| Tag Suggestions | Enable/disable auto-tag suggestions after save |
| Sentiment Analysis | Enable/disable mood detection for entries |
| Summarization | Enable/disable auto-summaries |
| Reflection Prompts | Enable/disable AI reflection questions |
| Writer's Block Helper | Enable/disable continuation suggestions |
| Ollama Status | Shows connection status and model availability |
| Pull Embedding Model | Downloads `nomic-embed-text` for semantic features |

### Data Management

| Action | Description |
|--------|-------------|
| Import | Import entries from file |
| Export Markdown | Download entries as markdown ZIP |
| Export HTML | Download entries as styled HTML |
| Export PDF | Download entries as PDF |
| Deduplicate | Find and remove duplicate entries |
| Reset Database | Delete all data (irreversible, requires confirmation) |

### Backup & Sync

| Action | Description |
|--------|-------------|
| Export Backup | Download full backup (.tar.gz) |
| Import Backup | Restore from backup file |
| Cloud Provider | Configure cloud backup |
| Schedule | Set automatic backup times |

---

## 21. Keyboard Shortcuts

### Global

| Shortcut | Action |
|----------|--------|
| `Ctrl+K` | Open global search palette |
| `Esc` | Close current modal/overlay/panel |

### Editor

| Shortcut | Action |
|----------|--------|
| `Ctrl+B` | Bold |
| `Ctrl+I` | Italic |
| `Ctrl+U` | Strikethrough |
| `Ctrl+K` | Inline code |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+F` | Find & replace |
| `Ctrl+S` | Save entry |

### Search Palette

| Shortcut | Action |
|----------|--------|
| `↑` / `↓` | Navigate results |
| `Enter` | Open selected entry |
| `Esc` | Close search |

---

## 22. Plugins

Diarilinux supports a plugin architecture for extending functionality.

### Installing a Plugin

1. Go to **Settings** → **Plugins**
2. Click **"Install Plugin"**
3. Provide:
   - **Name** — plugin identifier
   - **Version** — plugin version
   - **Description** — what the plugin does
   - **Entry point** — Python module path (e.g., `my_plugin.main`)
4. Click **Install**

### Managing Plugins

- **Enable/Disable** — toggle plugins without uninstalling
- **View hooks** — see which app events a plugin responds to
- **Uninstall** — remove a plugin completely
- **Priority** — plugins run in priority order when multiple handle the same event

---

## 23. Troubleshooting

### App Won't Start

**Desktop (from source):**
```bash
# Ensure dependencies are installed
cd backend && uv sync
cd ../frontend && npm install

# Check if ports are available
./dev.sh
```

**Desktop (installed):**
- Linux: Check if AppImage has execute permission (`chmod +x`)
- Windows: Run as administrator if needed
- macOS: Right-click → Open if blocked by Gatekeeper

### Database Issues

If you see database errors:

1. **Backup your data** first
2. Go to Settings → Reset Database (last resort)
3. Or restore from a backup file

### Search Not Finding Entries

- The search index rebuilds automatically on startup if stale
- Try restarting the application to trigger a reindex
- Check that entries are not marked as deleted

### Ollama/AI Not Working

1. Verify Ollama is running: `ollama list`
2. Check the model is installed: `ollama pull llama3.2:3b`
3. Verify the URL in Settings matches your Ollama endpoint (default: `http://localhost:11434`)

### Media Upload Fails

- Check file size (max 25 MB)
- Verify the file type is supported
- Check disk space for media storage
- Look for error messages in the upload status

### Voice Recording Not Working

- Grant microphone permissions in your browser/system
- Check that no other application is using the microphone
- Desktop: ensure Whisper model is configured correctly

### Data Storage Locations

| Platform | Database | Media |
|----------|----------|-------|
| Linux | `~/.local/share/diarilinux/diarilinux.db` | `~/.local/share/diarilinux/media/` |
| Windows | `%APPDATA%\diarilinux\diarilinux.db` | `%APPDATA%\diarilinux\media\` |
| macOS | `~/Library/Application Support/diarilinux/diarilinux.db` | `~/Library/Application Support/diarilinux/media/` |
| Dev mode | `./dev.db` | `./media/` |

### Getting Help

- **Issues**: Report bugs at the project's GitHub Issues page
- **Logs**: Check the terminal/console for error messages
- **Data recovery**: Always maintain regular backups

---

## Appendix A: Quick Reference Card

```
╔══════════════════════════════════════════════════╗
║              DIARILINUX QUICK REFERENCE          ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║  NAVIGATION                                      ║
║  Ctrl+K    Search          Esc    Close overlay  ║
║                                                  ║
║  EDITOR                                          ║
║  Ctrl+B    Bold            Ctrl+I  Italic        ║
║  Ctrl+U    Strikethrough   Ctrl+K  Inline code   ║
║  Ctrl+Z    Undo            Ctrl+Y  Redo          ║
║  Ctrl+F    Find/Replace    Ctrl+S  Save          ║
║                                                  ║
║  MARKDOWN                                        ║
║  **bold**  *italic*     ~~strike~~  `code`       ║
║  # H1      ## H2        > quote     - list       ║
║  [link]()  ![img]()     | table |                ║
║                                                  ║
║  VIEWS                                           ║
║  Calendar  Timeline  Search  Analytics  Map      ║
║  Digest  Reminders  On This Day  Settings        ║
║                                                  ║
╚══════════════════════════════════════════════════╝
```
