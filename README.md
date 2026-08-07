# 📔 LifeLogr

**Privacy-first, local-first journaling for Linux.** A single-user app for daily
journaling and rich notes — with on-device OCR (Tesseract), read-aloud (Edge TTS),
hybrid search, end-to-end encryption, optional cloud backup, and AI assistance that
runs **locally by default** (Ollama) and can optionally use a cloud model of your
choice. **Your journal lives on your machine.**

`v0.10.1` · Built for **Ubuntu 24.04 LTS** (and similar modern Linux distros).

![LifeLogr](docs/images/lifelogr_01.jpg)
![Editor](docs/images/lifelogr_Editor.jpg)

---

## ✨ Highlights

- **Journal & Notes** — date-bound entries (mood, templates, media, voice & video
  clips) plus a full **Notes** workspace: **nested folders**, tabbed pages, markdown,
  **inline `#tags`**, and encryption.
- **Clip & OCR** — snippet a region of your screen (`Ctrl+Shift+S`, desktop) or clip
  a web page, embed it as a picture, and **OCR the text** straight into the note —
  instantly searchable.
- **AI writing assistant** — grammar/spell check, rewrite, summarize, key points,
  tone, tag suggestions, themes, sentiment, reflection prompts and more. Runs
  **locally via Ollama by default**; optionally point it at any OpenAI-compatible
  cloud provider (OpenAI, Groq, OpenRouter, Kimi/Moonshot, Gemini, or a custom
  endpoint). See [🔐 Privacy & the AI model](#-privacy--the-ai-model).
- **Hybrid search** — full-text (SQLite FTS5) **plus** semantic vector search,
  unified across entries and notes (`Ctrl+K`).
- **Read aloud** — Microsoft Edge TTS with voice / rate / volume / pitch controls and
  a disk cache.
- **Encrypt** individual entries or notes (AES-256-GCM, scrypt-derived keys,
  per-item salt).
- **Stay organized** — Reminders with desktop notifications, **inline `#tags`** (with
  autocomplete as you type), templates, and a daily writing prompt.
- **Backup** — scheduled local backup plus **Google Drive, OneDrive, Dropbox, Box**
  (OAuth) and **WebDAV / Synology NAS**. Cloud credentials are stored encrypted.
- **Two ways to run** — a native **desktop app** (Tauri) or a lightweight **web app**
  (browser).

---

## 🔐 Privacy & the AI model

LifeLogr is built local-first. Out of the box **nothing leaves your machine**:

- The backend binds to **`127.0.0.1` only** (loopback, single-user, no auth).
- **AI runs on-device via Ollama**, and **OCR via Tesseract** — both fully offline.
- **Web-clipping** fetches a URL server-side but only the *URL* leaves the device;
  your journal content never does.
- Cloud backup/sync is **opt-in** and uses OAuth; tokens are encrypted at rest.

### Optional cloud AI (opt-in)

You can optionally route AI through a cloud model in **Settings → AI** (e.g. for a
larger model than your CPU can run). Any provider that speaks the OpenAI
chat-completions API works: **OpenAI, Groq, OpenRouter, Kimi/Moonshot, Google
Gemini**, or a **Custom** endpoint. API keys are AES-GCM encrypted at rest and never
returned by the API. **Ollama remains the automatic fallback** if the active cloud
provider is unreachable.

When a cloud model is active, LifeLogr is explicit about it: the **Settings →
Privacy** tab shows a live **egress report** — a per-surface table stating exactly
what leaves the device (AI tools, embeddings, cloud backup) and a warning banner in
the AI tab. The default stays local.

---

## 🏗️ Architecture

```
backend/    FastAPI (async) + SQLAlchemy 2.x + SQLite (WAL) + FTS5/embeddings
frontend/   Vue 3 SPA · Vite · TypeScript · Pinia · TailwindCSS v4
desktop/    Tauri v2 (Rust) shell + PyInstaller-bundled backend sidecar
scripts/    build-web-deb.sh  → browser-served package
mobile/     Capacitor scaffolding (not yet implemented)
```

- The **backend** is a FastAPI server bound to `127.0.0.1` (loopback only — single-user/local).
- The **frontend** is a Vue 3 SPA. In the desktop app it runs inside the Tauri webview;
  in the web app it's served by the backend as static files.
- **AI/ML** runs locally by default: [Ollama](https://ollama.com) for text AI,
  [Tesseract](https://github.com/tesseract-ocr/tesseract) for OCR. No GPU required
  (a small CPU-friendly model like `gemma3:4b` is recommended).

---

## 📦 Installation

LifeLogr ships as two `.deb` packages. Pick one.

### Option A — Desktop app (Tauri)  ·  *required for screen-snipping*
A native window; bundles everything (no install-time network needed). This is the
**only** build that supports screen-snippet capture.

```bash
sudo dpkg -i LifeLogr_0.10.1_amd64.deb
sudo apt-get install -f        # pulls tesseract-ocr, gstreamer, webkit, etc.
```
Launch **LifeLogr** from your app menu.

### Option B — Web app (browser)
Lighter; the backend serves the SPA and you use it in a browser tab. The Python
virtualenv is built **on your machine at install time** (needs network).

```bash
sudo dpkg -i lifelogr-web_0.10.1_amd64.deb
sudo apt-get install -f        # pulls python3 (≥3.11), tesseract-ocr
```
Launch **LifeLogr** from your app menu (or run `lifelogr`); it opens a browser tab on
a free local port. Stop it with `lifelogr --stop`.

> **After any upgrade:** fully **quit** the running app before relaunching (closing the
> window can leave the old process running). For the web app: `lifelogr --stop`.

### Option C — Run from source (development)
```bash
# backend
cd backend && uv sync
uv run uvicorn app.main:app --reload --port 8000

# frontend (another terminal)
cd frontend && npm install
npm run dev          # → http://localhost:5173
```
Prerequisites: Python 3.11+, Node 20+, [`uv`](https://docs.astral.sh/uv/), and
optionally Ollama + Tesseract for AI/OCR.

---

## 🖥️ Two ways to run

| | **Desktop (Tauri)** | **Web (browser)** |
|---|---|---|
| Runtime | Native window + bundled backend | Backend serves SPA; browser tab |
| Screen-snippet (`Ctrl+Shift+S`) | ✅ | ❌ (browsers can't capture the screen) |
| Web-clip (text) | ✅ | ✅ |
| OCR | ✅ (screen snip + image upload) | ✅ (image upload) |
| Deb size | ~63 MB | ~17 MB |
| Install-time network | Not required | Required (builds the venv) |
| **Data directory** | `~/.local/share/com.lifelogr.desktop/` | `~/.local/share/lifelogr/` |

¹ The two builds use **separate databases** by default. To see the same journal in
both, point one at the other's data dir via **Settings → Data → Storage location**
(carry the `.secret_key` so encrypted items still decrypt).

---

## 📁 Where your data lives

Everything is local, under a single data directory (see the table above for the
per-build default):

```
<data-dir>/
  lifelogr.db          # SQLite database (entries, notes, reminders, …)
  lifelogr.db.boot-bak-* # rotating boot snapshots — auto-restored if the DB corrupts
  .secret_key          # do NOT delete — encrypts your data
  media/               # uploaded images/audio/video
  tts/                 # read-aloud audio cache
  backups/             # scheduled local backups
  server.log           # web-app log (web build only)
```

> **Never delete `.secret_key`** — encrypted entries/notes cannot be decrypted
> without it.

---

## ✂️ Clipping & OCR

**Screen snip (Notes, desktop only):**
1. Open a (non-encrypted) note and trigger a snip — **`Ctrl+Shift+S`** (global) or
   the **✂️ scissors** toolbar button.
2. Drag a rectangle over the region you want. The capture is embedded into the note
   as a picture.
3. **OCR runs automatically** and the recognized text is inserted beneath the image
   in a collapsible block — and becomes **searchable** (FTS-indexed).

**Image uploads (Journal & Notes, both builds):** attach an image (paperclip or
drag-and-drop) to an entry or note and it's **embedded inline in the body**, then
**OCR runs automatically** and the text is inserted beneath it — the same flow in the
desktop and the web app.

**🌐 Web-clip** (globe button, both builds) fetches a URL's text via a server-side,
SSRF-hardened extractor and inserts it as markdown.

**OCR language:** **English** or **Tamil** — set in **Settings → Appearance → OCR
language**. OCR runs on-device via Tesseract (auto-installed via the deb's `Depends`);
the desktop build additionally uses PipeWire at runtime for screen capture (present by
default on Ubuntu). Tamil needs the `tesseract-ocr-tam` data pack — the desktop deb
ships English, so install Tamil separately (`sudo apt install tesseract-ocr-tam`) if
you use it.

---

## 🔧 Development

```bash
make setup    # sync backend deps + npm install
make test     # backend pytest
make lint     # ruff + mypy (strict)
```

### Build packages
```bash
# Desktop deb + AppImage (Tauri) — needs libpipewire-0.3-dev to build the snip feature
cd desktop && make build
# → desktop/src-tauri/target/release/bundle/{deb,appimage}/

# Web deb
./scripts/build-web-deb.sh
# → dist/lifelogr-web_<ver>_amd64.deb
```

The `snip` (screen-capture) capability is a Cargo **feature** that's **on by
default** (`default = ["snip"]`). The `devtools` feature (webview inspector) is
intentionally **excluded** from default so the inspector never ships in a release
build. Build without `snip` on machines lacking `libpipewire-0.3-dev`:
```bash
cd desktop/src-tauri && cargo tauri build --no-default-features
```

---

## ⌨️ Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Global search palette | `Ctrl+K` |
| Screen snip (desktop) | `Ctrl+Shift+S` |
| Save | `Ctrl+S` |
| Find & replace | `Ctrl+F` |
| Zen mode (distraction-free) | `Ctrl+.` |
| Bold / Italic / Strikethrough | `Ctrl+B` / `Ctrl+I` / `Ctrl+Shift+X` |
| Clear formatting | `Ctrl+\` |
| Inline code (in editor) | <code>Ctrl+E</code> |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Close overlay / modal | `Esc` |

---

## 🧪 Quality

- Backend: `pytest` suite, **mypy strict**, **ruff** — all required to pass on `main`.
- Frontend: `vue-tsc` type-check, **Vitest** unit tests, Playwright e2e.
- A security review is recommended before merging networked endpoints (the
  `/notes/web-clip` SSRF surface and the OAuth callback paths are hardened and tested).

---

## 📑 SDD pipeline & project docs

System blueprints are generated via a Spec-Driven Development pipeline:

| Phase | Command | Document | Purpose |
| :--- | :--- | :--- | :--- |
| p0 | `make domain` | [DOMAIN.md](docs/00-domain/DOMAIN.md) | Bounded contexts & domain models |
| p1 | `make reqs` | [REQUIREMENTS.md](docs/01-requirements/REQUIREMENTS.md) | Functional & non-functional requirements |
| p2 | `make spec` | [SPEC.md](docs/02-spec/SPEC.md) | Schema models & API contract |
| p3 | `make review` | [REVIEW.md](docs/03-review/REVIEW.md) | Quality gate (PASS required) |
| p4 | `make design` | [DESIGN.md](docs/04-design/DESIGN.md) | Module mapping & sequence diagrams |

Further reading: [Architecture & Developer Guide](docs/ARCHITECTURE.md) ·
[User Manual](docs/manual/USER_MANUAL.md) ·
[API Reference](docs/manual/API_REFERENCE.md) ·
[Deployment](docs/manual/DEPLOYMENT.md) ·
[Build Guide](docs/BUILD_GUIDE.md).

---

## 🩺 Troubleshooting

- **App didn't change after upgrading** — the old process is still running. Fully quit
  it (`lifelogr --stop` for the web app, or quit from the app menu) and relaunch.
- **OCR fails with "install tesseract"** — `sudo apt install tesseract-ocr` (or
  Settings → About → System Setup on desktop).
- **Screen snip does nothing (desktop)** — another app may have grabbed
  `Ctrl+Shift+S`; use the ✂️ toolbar button. On Wayland, approve the screen-capture
  portal prompt.
- **AI tools hang** — likely a "thinking" model on CPU. Use a non-thinking model such
  as `gemma3:4b` (Settings → AI).
- **Port clashes in dev** — if `:8000` is taken the backend binds silently elsewhere;
  set an explicit `--port` and `VITE_BACKEND_PORT`.

---

## 📝 Credits

Built by Meeran. Source: [github.com/emeeran/LifeLogr](https://github.com/emeeran/LifeLogr).
See **Settings → About** in the app for version and credits.
