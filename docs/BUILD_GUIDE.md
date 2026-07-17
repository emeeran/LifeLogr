# LifeLogr — Build, Update & Install Guide

Complete guide for building, updating, and installing LifeLogr on **Linux**, **Windows**, and **macOS**.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Building the AppImage / MSI / DMG](#2-building)
3. [Updating an Existing Build](#3-updating)
4. [Installing on Linux](#4-linux)
5. [Installing on Windows](#5-windows)
6. [Installing on macOS](#6-macos)
7. [First-Run Setup (System Dependencies)](#7-first-run-setup)
8. [Configuration](#8-configuration)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

All platforms need:

| Tool | Version | Install |
|------|---------|---------|
| **Rust** | stable | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| **Node.js** | 20+ | [nodejs.org](https://nodejs.org) or `nvm install 20` |
| **Python** | 3.11+ | System package manager |
| **uv** | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **UPX** | any | Linux: `sudo apt install upx-ucl` · macOS: `brew install upx` · Windows: `choco install upx` |

### Platform-specific prerequisites

**Linux (Ubuntu/Debian):**
```bash
sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev \
  libayatana-appindicator3-dev librsvg2-dev upx-ucl
```

**Windows:**
- Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (C++ workload)
- WebView2 is pre-installed on Windows 11; the installer handles Windows 10

**macOS:**
- Xcode Command Line Tools: `xcode-select --install`

---

## 2. Building

### Quick Build (single command)

```bash
cd desktop
make install   # First time only — installs all deps
make build     # Builds frontend + backend + native package
```

The output goes to `desktop/src-tauri/target/release/bundle/`:
- **Linux**: `appimage/LifeLogr_0.2.0_amd64.AppImage` + `deb/LifeLogr_0.2.0_amd64.deb`
- **Windows**: `msi/LifeLogr_0.2.0_x64_en-US.msi`
- **macOS**: `dmg/LifeLogr_0.2.0_aarch64.dmg`

> **Versioning:** the package version is sourced from `backend/pyproject.toml`, `desktop/src-tauri/Cargo.toml`, and `desktop/src-tauri/tauri.conf.json` — bump all three together. The version shown in the app's **About** tab comes from `APP_VERSION` in `backend/app/core/config.py` (served via the `/api/v1/settings` endpoint), so update that too or the UI will lag behind the package version. The artifact filenames above reflect whatever version you set.
>
> **TTS (Read Aloud):** `edge_tts` is bundled automatically — `scripts/build.sh` runs `uv sync --extra tts` and the PyInstaller spec collects the `edge_tts` submodules. No extra steps needed.

### Step-by-Step Build

If you want more control over each step:

```bash
# 1. Build the Vue.js frontend
cd frontend && npm install && npm run build

# 2. Build the Python backend into a single binary
cd ../backend && uv sync
uv run pyinstaller ../desktop/scripts/pyinstaller.spec \
  --noconfirm \
  --distpath ../desktop/dist \
  --workpath ../desktop/build/pyinstaller

# 3. Copy backend binary as Tauri sidecar
#    Linux:
mkdir -p ../desktop/src-tauri/binaries
cp dist/lifelogr-backend ../desktop/src-tauri/binaries/lifelogr-backend-x86_64-unknown-linux-gnu
chmod +x ../desktop/src-tauri/binaries/lifelogr-backend-x86_64-unknown-linux-gnu
#    Windows:
#      copy dist\lifelogr-backend.exe ..\desktop\src-tauri\binaries\lifelogr-backend-x86_64-pc-windows-msvc.exe
#    macOS (Apple Silicon):
#      cp dist/lifelogr-backend ../desktop/src-tauri/binaries/lifelogr-backend-aarch64-apple-darwin

# 4. Build the native Tauri package
cd ../desktop/src-tauri
#    Linux:
cargo tauri build --bundles appimage,deb
#    Windows:
#      cargo tauri build --bundles msi
#    macOS:
#      cargo tauri build --bundles dmg
```

### Build Output Sizes

| Platform | Expected Size | Notes |
|----------|--------------|-------|
| Linux AppImage | ~80-100 MB | webkit2gtk adds ~60MB (unavoidable) |
| Windows MSI | ~50-70 MB | Uses Edge WebView2 (pre-installed) |
| macOS DMG | ~40-60 MB | Uses system WebKit |

---

## 3. Updating

When you make code changes and want to rebuild:

```bash
# Quick rebuild (from project root)
cd desktop && make build

# Or rebuild just one part:
make build-frontend    # Frontend only (Vue changes)
make build-backend     # Backend only (Python changes)
make build-sidecar     # Backend + copy to Tauri
make build             # Everything + package
```

### After pulling new code from git

```bash
cd desktop
make install    # Re-sync deps (safe to re-run)
make build      # Full rebuild
```

### Updating dependencies

```bash
# Frontend deps
cd frontend && npm update && npm run build

# Backend deps
cd backend && uv lock --upgrade && uv sync

# Rust deps
cd desktop/src-tauri && cargo update
```

### Reinstalling the .deb over a running version

`dpkg -i` replaces the on-disk binaries, but a **running** LifeLogr keeps the old binary in memory and holds port 18765 — so the new version won't take effect until you fully restart. After installing a new `.deb`:

```bash
# Quit LifeLogr from the UI first (save any open entry), then clear lingering procs:
pkill -f lifelogr-backend
pkill -f /usr/bin/lifelogr
# Relaunch from your application menu — it spawns the new backend on 18765
```

If the **About** tab still shows the old version after reopening, a stale `lifelogr-backend` process is almost always the cause.

### Clean build (start fresh)

```bash
cd desktop && make clean && make build
```

---

## 4. Installing on Linux

### Option A: AppImage (recommended, no root needed)

```bash
# 1. Download or copy the AppImage
cp desktop/src-tauri/target/release/bundle/appimage/LifeLogr_0.2.0_amd64.AppImage ~/Applications/

# 2. Make it executable
chmod +x ~/Applications/LifeLogr_0.2.0_amd64.AppImage

# 3. Run it
~/Applications/LifeLogr_0.2.0_amd64.AppImage
```

To add to your application launcher:
```bash
# Create a desktop entry
cat > ~/.local/share/applications/lifelogr.desktop << 'EOF'
[Desktop Entry]
Name=LifeLogr
Exec=/home/YOUR_USER/Applications/LifeLogr_0.2.0_amd64.AppImage
Icon=lifelogr
Type=Application
Categories=Office;Utility;
Comment=Privacy-first journaling app
EOF
```

### Option B: .deb package (Debian/Ubuntu)

```bash
sudo dpkg -i desktop/src-tauri/target/release/bundle/deb/LifeLogr_0.2.0_amd64.deb

# Then launch from your application menu, or:
lifelogr
```

### Option C: From source (development)

```bash
# Terminal 1 — backend
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend
cd frontend && npm run dev
```
Open http://localhost:5173 in your browser.

### Data storage location (Linux)

| Data | Path |
|------|------|
| Database | `~/.local/share/com.lifelogr.desktop/lifelogr.db` |
| Media files | `~/.local/share/com.lifelogr.desktop/media/` |
| Config | Set via `DIARI_DATA_DIR` env var |

---

## 5. Installing on Windows

### From MSI installer

1. Double-click `LifeLogr_0.2.0_x64_en-US.msi`
2. Follow the installer wizard
3. If prompted about WebView2, allow the installer to download it
4. Launch from **Start Menu → LifeLogr**

### From source (development)

```powershell
# Terminal 1 — backend
cd backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```
Open http://localhost:5173 in your browser.

### Data storage location (Windows)

| Data | Path |
|------|------|
| Database | `%APPDATA%\lifelogr\lifelogr.db` |
| Media files | `%APPDATA%\lifelogr\media\` |
| Config | Set via `DIARI_DATA_DIR` env var |

### Building on Windows

```powershell
cd desktop
make install
make build
# Output: src-tauri\target\release\bundle\msi\LifeLogr_0.2.0_x64_en-US.msi
```

---

## 6. Installing on macOS

### From DMG

1. Double-click `LifeLogr_0.2.0_aarch64.dmg`
2. Drag **LifeLogr** to the **Applications** folder
3. Launch from Applications or Spotlight

**Gatekeeper warning:** Since the app is unsigned, macOS will show a warning on first launch. To bypass:
- Right-click the app → **Open** → Click **Open** in the dialog
- Or: `System Settings → Privacy & Security → Open Anyway`

### From source (development)

```bash
# Terminal 1 — backend
cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend
cd frontend && npm run dev
```
Open http://localhost:5173 in your browser.

### Data storage location (macOS)

| Data | Path |
|------|------|
| Database | `~/Library/Application Support/lifelogr/lifelogr.db` |
| Media files | `~/Library/Application Support/lifelogr/media/` |
| Config | Set via `DIARI_DATA_DIR` env var |

### Building on macOS

```bash
cd desktop
make install
make build
# Output: src-tauri/target/release/bundle/dmg/LifeLogr_0.2.0_aarch64.dmg
```

> **Note:** The macOS build targets Apple Silicon (M1/M2/M3/M4) by default. Intel Mac users can run it via Rosetta 2 (transparent). To build for Intel specifically, change the sidecar filename to `lifelogr-backend-x86_64-apple-darwin`.

---

## 7. First-Run Setup (System Dependencies)

The app works out-of-the-box for core features (entries, tags, search, templates, media). Some advanced features need system-level tools installed separately.

### Using the built-in setup (Linux, Tauri app only)

1. Launch LifeLogr
2. Open **Settings** (gear icon in sidebar)
3. Scroll to **System Setup** section
4. Click **Install Missing Dependencies**
5. Enter your password when prompted
6. Wait for installation to complete (~5 min for Ollama model download)
7. Restart the app

This installs:
- **Tesseract OCR** — image-to-text extraction
- **Ollama + llama3.2:3b** — AI grammar check, spell check, rewrite
- **Ollama + nomic-embed-text** — semantic search, similar entries, mood analysis
- **WeasyPrint system libs** — PDF export (pango, cairo, gdk-pixbuf)

### Manual setup (any platform)

**Linux (Ubuntu/Debian):**
```bash
sudo apt install tesseract-ocr libpango-1.0-0 libpangocairo-1.0-0 \
  libcairo2 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info

# Ollama for AI features
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

**Linux (Fedora/RHEL):**
```bash
sudo dnf install tesseract pango cairo gdk-pixbuf2 libffi shared-mime-info
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

**Linux (Arch):**
```bash
sudo pacman -S tesseract pango cairo gdk-pixbuf2 libffi shared-mime-info
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

**macOS:**
```bash
brew install tesseract
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

**Windows:**
```powershell
# Tesseract OCR
winget install UB-Mannheim.TesseractOCR

# Ollama
winget install Ollama.Ollama
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### Feature dependency map

| Feature | What it needs | Install method |
|---------|--------------|----------------|
| Core (entries, tags, search, templates) | Nothing extra | Works out of the box |
| TTS (Read Aloud) | Nothing extra | Built in (edge-tts) |
| Encryption | Nothing extra | Built in (cryptography) |
| Scheduled backups | Nothing extra | Built in (APScheduler) |
| OCR (image text extraction) | Tesseract OCR | Setup script or manual |
| AI grammar/spell check/rewrite | Ollama + llama3.2 model | Setup script or manual |
| Semantic search, similar entries | Ollama + nomic-embed-text model | `ollama pull nomic-embed-text` |
| Sentiment analysis, mood timeline | Ollama + llama3.2 model | Auto-runs after entry save |
| Weekly digest | Ollama + llama3.2 model | Auto-generates weekly (Sun 2 AM) |
| Auto-tag suggestions | Ollama + llama3.2 model | Auto-runs after entry save |
| Writer's block helper | Ollama + llama3.2 model | On-demand from editor |
| On This Day reflection | Ollama + llama3.2 model | On-demand from sidebar |
| Recurring theme detection | Ollama + llama3.2 model | On-demand from analytics |
| PDF export | pango, cairo, gdk-pixbuf | Setup script or manual |
| Voice transcription | faster-whisper (~1GB) | Optional Python dep |

---

## 8. Configuration

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DIARI_DATA_DIR` | Platform-specific (see above) | Data directory (DB, media) |
| `APP_ENV` | `development` | Set to `production` in packaged apps |
| `SECRET_KEY` | `change-me-before-production` | **Must be changed in production** |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
| `OLLAMA_MODEL` | `llama3.2:3b` | AI model name |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model for semantic search |
| `OLLAMA_TIMEOUT_SECONDS` | `300` | AI request timeout |
| `AI_ENABLE_EMBEDDINGS` | `true` | Enable semantic search and similar entries |
| `AI_ENABLE_TAG_SUGGESTIONS` | `true` | Enable auto-tag suggestions |
| `AI_ENABLE_SENTIMENT` | `true` | Enable sentiment analysis |
| `AI_ENABLE_SUMMARIZATION` | `true` | Enable auto-summaries |
| `AI_ENABLE_REFLECTION_PROMPTS` | `true` | Enable AI reflection prompts |
| `AI_ENABLE_WRITER_BLOCK_HELPER` | `true` | Enable writer's block continuation |
| `WHISPER_MODEL` | `base` | Whisper STT model size |
| `WHISPER_DEVICE` | `cpu` | Set to `cuda` for GPU acceleration |

> **Note:** SQLite connection pool is automatically set to `pool_size=1` with no overflow. `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` settings only apply to PostgreSQL.

### Custom data directory

```bash
# Linux/macOS
DIARI_DATA_DIR=/path/to/data ./LifeLogr_0.2.0_amd64.AppImage

# Or set permanently
export DIARI_DATA_DIR=/path/to/data
```

### Backend port

The Tauri app hardcodes the backend to port **18765**. For development mode, the default port is **8000** (configurable via `--port`).

---

## 9. Troubleshooting

### AppImage won't launch

```bash
# Make sure it's executable
chmod +x LifeLogr_0.2.0_amd64.AppImage

# If FUSE is missing (some distros)
sudo apt install libfuse2

# Run with debug output
./LifeLogr_0.2.0_amd64.AppImage --verbose
```

### "Backend failed to start" error

The Python sidecar takes a few seconds to start. The frontend retries for 15 seconds. If it still fails:

```bash
# Test the backend binary directly
./desktop/dist/lifelogr-backend --host 127.0.0.1 --port 18765

# Check if port is already in use
lsof -i :18765
```

### Ollama not connecting

```bash
# Check if Ollama is running
ollama list

# Start it manually
ollama serve

# Check the main model is pulled
ollama pull llama3.2:3b

# Pull the embedding model for semantic search
ollama pull nomic-embed-text
```

### OCR not working

```bash
# Verify Tesseract is installed
tesseract --version

# Install if missing
sudo apt install tesseract-ocr   # Debian/Ubuntu
sudo dnf install tesseract        # Fedora
brew install tesseract            # macOS
```

### Windows: WebView2 missing

The MSI installer downloads WebView2 automatically. If it fails:
1. Download from [Microsoft](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
2. Install the "Evergreen Bootstrapper"
3. Re-run LifeLogr

### macOS: "App is damaged and can't be opened"

```bash
# Remove quarantine attribute
xattr -cr /Applications/LifeLogr.app
```

### Build fails with "pyinstaller not found"

```bash
# Use uv to run pyinstaller from the project venv
cd backend && uv sync
uv run pyinstaller --version   # Should print version
```

### UPX not compressing

```bash
# Verify UPX is installed
upx --version

# Install if missing
sudo apt install upx-ucl       # Debian/Ubuntu
brew install upx                # macOS
choco install upx               # Windows
```

### Rebuild from scratch

```bash
cd desktop
make clean
make install
make build
```

---

## Quick Reference

```bash
# ── First time ──
cd desktop && make install && make build

# ── After code changes ──
cd desktop && make build

# ── Install system deps (Linux) ──
cd desktop && make setup

# ── Development mode ──
cd backend && uv run uvicorn app.main:app --reload
cd frontend && npm run dev

# ── Clean everything ──
cd desktop && make clean
```
