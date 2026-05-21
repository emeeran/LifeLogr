# Cross-Platform Desktop Packaging — Lightweight Builds

## Context
Diarilinux needs lightweight native desktop packages for **Linux (AppImage), Windows (MSI), and macOS (DMG)** with ALL features intact. The current AppImage is 114MB (38MB Python backend + ~16MB Rust binary + ~60MB webkit2gtk). This plan optimizes size while fixing cross-platform build issues.

**Tech stack**: Tauri 2.0 + PyInstaller sidecar (Python 3.11 FastAPI backend, Vue 3 + Vite frontend, SQLite).

**Current sizes**: Backend binary 38MB, frontend dist 444KB, AppImage 114MB, Rust binary ~16MB.

---

## Phase 1: Fix Build Tooling Bugs

### 1.1 Fix Makefile — use `uv run pyinstaller`

**File:** `desktop/Makefile`

Current `build-backend` uses bare `pyinstaller` (system Python, not project venv). The `install` target uses `pip install pyinstaller` instead of `uv sync`. Sidecar copy only handles Linux triple.

**Changes:**
- Replace `pip install pyinstaller` with `cd ../backend && uv sync` in `install` target
- Replace bare `pyinstaller` with `uv run pyinstaller` in `build-backend`
- Add platform detection with target-triple mapping:
  - Linux: `x86_64-unknown-linux-gnu`
  - Windows: `x86_64-pc-windows-msvc.exe`
  - macOS (Apple Silicon): `aarch64-apple-darwin`
  - macOS (Intel): `x86_64-apple-darwin`
- Fix sidecar copy to use detected triple
- Add unified `build` target that detects OS

### 1.2 Fix CI workflow for `uv`

**File:** `.github/workflows/build.yml`

Every platform job uses `pip install -r requirements.txt` (file doesn't exist — project uses `uv`).

**Changes for all desktop jobs:**
- Add `astral-sh/setup-uv@v4` step
- Replace `pip install -r requirements.txt` with `cd backend && uv sync`
- Replace bare `pyinstaller` with `uv run pyinstaller`
- Add sidecar rename/copy step with correct platform triple
- Install UPX on each platform (`apt install upx-ucl`, `choco install upx`, `brew install upx`)
- Remove mobile jobs (Android/iOS) — out of scope for this task

---

## Phase 2: Complete PyInstaller Hidden Imports

**File:** `desktop/scripts/pyinstaller.spec`

Current spec is missing many routers, services, models, and schemas. If PyInstaller's static analysis misses them, the binary crashes at runtime.

**Recommended: Replace manual list with auto-discovery:**
```python
from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules('app')
```

This automatically discovers all `app.*` submodules and future-proofs against additions.

**Also add missing hidden imports for third-party packages:**
- `aiosqlite`, `edge_tts`, `httpx`
- `apscheduler.schedulers.asyncio`, `apscheduler.triggers.cron`
- `uvicorn.*` (all existing entries stay)
- `sqlalchemy.ext.asyncio`, `sqlalchemy.orm`

---

## Phase 3: Optimize Binary Size

### 3.1 Install and verify UPX compression

UPX is set to `True` in the spec but **not installed** on the system — PyInstaller silently skips it.

**Actions:**
- Install UPX: `sudo apt install upx-ucl` (Linux), `brew install upx` (macOS), `choco install upx` (Windows)
- Rebuild and compare sizes
- **Expected:** 38MB → 20-25MB (30-50% reduction)

### 3.2 Add Python stdlib excludes

```python
excludes=[
    # Heavy optional deps (existing)
    'faster_whisper', 'weasyprint', 'torch', 'numpy', 'scipy', 'matplotlib',
    # Unused stdlib
    'tkinter', 'unittest', 'test', 'tests', 'xmlrpc', 'pydoc', 'doctest',
    'distutils', 'lib2to3', 'multiprocessing', 'curses', 'tty',
    'webbrowser', 'antigravity', 'this',
    'imaplib', 'nntplib', 'smtplib', 'poplib', 'telnetlib', 'ftplib',
]
```

**Expected:** 2-5MB additional savings.

### 3.3 Add Rust LTO and size optimization

**File:** `desktop/src-tauri/Cargo.toml`

Add `[profile.release]` section:
```toml
[profile.release]
lto = true          # Link-Time Optimization
opt-level = "z"     # Optimize for size
strip = true        # Strip debug symbols
codegen-units = 1   # Better optimization
panic = "abort"     # Smaller binary (no unwind tables)
```

**Expected:** 16MB → 8-12MB.

### 3.4 Conditional console for Windows

In `pyinstaller.spec`:
```python
import sys
exe = EXE(
    ...
    console=sys.platform != 'win32',  # Hide cmd window on Windows
)
```

### 3.5 Size targets summary

| Component | Current | Target | Method |
|-----------|---------|--------|--------|
| Python backend | 38MB | 20-25MB | UPX + stdlib excludes |
| Rust Tauri binary | 16MB | 8-12MB | LTO + opt-level "z" + strip |
| Linux AppImage | 114MB | 80-100MB | Combined (webkit2gtk is ~60MB, unavoidable) |
| Windows MSI | N/A | 50-70MB | Uses Edge WebView2 (pre-installed) |
| macOS DMG | N/A | 40-60MB | Uses system WebKit |

---

## Phase 4: First-Run Setup Script (Linux)

The AppImage keeps the binary small by excluding system-level deps (tesseract, Ollama, weasyprint libs). A first-run setup script installs everything needed for full functionality.

### 4.1 Create setup script

**Create:** `desktop/scripts/setup-linux.sh`

Bundled as a Tauri resource and executed on first launch (or via Settings > Setup).

```bash
#!/usr/bin/env bash
# Diarilinux — First-run system dependency installer
# Run: sudo ./setup-linux.sh (or via the app's Setup dialog)
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ── Detect distro ──
if [ -f /etc/os-release ]; then
    source /etc/os-release
    DISTRO="$ID"
else
    fail "Cannot detect Linux distribution"
fi

# ── 1. System packages ──
install_system_deps() {
    local pkgs=(
        tesseract-ocr
        libpango-1.0-0 libpangocairo-1.0-0 libcairo2
        libgdk-pixbuf2.0-0 libffi-dev shared-mime-info
    )

    case "$DISTRO" in
        ubuntu|debian|linuxmint|pop)
            sudo apt-get update -qq
            sudo apt-get install -y --no-install-recommends "${pkgs[@]}"
            ;;
        fedora|rhel|centos)
            sudo dnf install -y tesseract pango cairo gdk-pixbuf2 libffi shared-mime-info
            ;;
        arch|manjaro|endeavouros)
            sudo pacman -S --needed --noconfirm tesseract pango cairo gdk-pixbuf2 libffi shared-mime-info
            ;;
        opensuse*|sles)
            sudo zypper install -y tesseract-ocr pango cairo gdk-pixbuf libffi shared-mime-info
            ;;
        *)
            warn "Unsupported distro: $DISTRO. Install manually: tesseract-ocr, pango, cairo, gdk-pixbuf"
            return
            ;;
    esac
    log "System packages installed"
}

# ── 2. Ollama (AI grammar/spell check) ──
install_ollama() {
    if command -v ollama &>/dev/null; then
        log "Ollama already installed"
    else
        curl -fsSL https://ollama.com/install.sh | sh
        log "Ollama installed"
    fi

    # Start service if not running
    if ! pgrep -x ollama &>/dev/null; then
        ollama serve &>/dev/null &
        sleep 3
    fi

    # Pull default model (configured in config.py as OLLAMA_MODEL)
    if ollama list 2>/dev/null | grep -q "llama3.2"; then
        log "Ollama model llama3.2 already available"
    else
        ollama pull llama3.2:3b
        log "Ollama model llama3.2:3b pulled"
    fi
}

# ── 3. Python optional deps (faster-whisper, weasyprint) ──
install_python_optional() {
    # These are excluded from the PyInstaller bundle but available via pip
    # They install into a dedicated venv alongside the AppImage
    local VENV="$HOME/.local/share/diarilinux/python-deps"

    if [ ! -d "$VENV" ]; then
        python3 -m venv "$VENV"
    fi

    "$VENV/bin/pip" install --upgrade pip -q
    "$VENV/bin/pip" install -q faster-whisper weasyprint 2>/dev/null || \
        warn "Some Python optional deps failed to install (non-critical)"

    log "Python optional deps installed to $VENV"
}

# ── 4. Verify ──
verify_install() {
    echo ""
    echo "=== Diarilinux Setup Verification ==="
    echo ""

    command -v tesseract &>/dev/null && log "Tesseract OCR: installed" || warn "Tesseract OCR: not found"
    command -v ollama &>/dev/null    && log "Ollama AI: installed"     || warn "Ollama AI: not found"
    ollama list 2>/dev/null | grep -q "llama3.2" && log "AI Model: llama3.2 available" || warn "AI Model: not pulled"

    echo ""
    log "Setup complete! Restart Diarilinux to use all features."
}

# ── Run all ──
echo "Diarilinux System Dependency Setup"
echo "==================================="
echo ""

install_system_deps
install_ollama
# install_python_optional  # Uncomment when faster-whisper/weasyprint support is added
verify_install
```

### 4.2 Integrate setup script into Tauri app

**Modify:** `desktop/src-tauri/src/main.rs`

Add a Tauri command to run the setup script:

```rust
#[tauri::command]
async fn run_setup(app: tauri::AppHandle) -> Result<String, String> {
    let resource = app.path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("scripts/setup-linux.sh");

    let output = std::process::Command::new("pkexec")
        .arg(&resource)
        .output()
        .map_err(|e| e.to_string())?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

#[tauri::command]
async fn check_deps() -> serde_json::Value {
    // Quick check of what's available
    let tesseract = std::process::Command::new("tesseract")
        .arg("--version")
        .output().is_ok();
    let ollama = std::process::Command::new("ollama")
        .arg("list")
        .output().is_ok();

    serde_json::json!({
        "tesseract": tesseract,
        "ollama": ollama,
        "all_installed": tesseract && ollama,
    })
}
```

Register the commands:
```rust
.invoke_handler(tauri::generate_handler![run_setup, check_deps])
```

### 4.3 Bundle script as Tauri resource

**Modify:** `desktop/src-tauri/tauri.conf.json`

Add under `bundle`:
```json
"resources": ["../scripts/setup-linux.sh"]
```

### 4.4 Frontend: Show setup prompt on first launch

**Modify:** `frontend/src/components/settings/SettingsView.vue`

Add a "System Setup" section that:
- Calls `check_deps()` on mount
- If `all_installed === false`, shows a warning banner with "Run Setup" button
- "Run Setup" button calls `run_setup()` via Tauri invoke
- Shows progress/output in a terminal-like panel

### 4.5 Dependency map (what each feature needs)

| Feature | System Dep | Python Dep (bundled) | Python Dep (NOT bundled) |
|---------|-----------|---------------------|--------------------------|
| OCR (image→text) | `tesseract-ocr` | pytesseract, Pillow | — |
| AI grammar/spell | `ollama` + model | httpx | — |
| TTS (text→speech) | — | edge-tts | — |
| PDF export | pango, cairo, gdk-pixbuf | markdown-it-py | weasyprint |
| Voice transcription | — | — | faster-whisper |
| Encryption | — | cryptography | — |
| Media (images) | — | Pillow | — |
| Search (FTS5) | — | aiosqlite | — |
| Scheduled backups | — | apscheduler | — |

**Bundled Python deps** work out-of-the-box (included in PyInstaller binary).
**System deps** need the setup script.
**Non-bundled Python deps** (faster-whisper, weasyprint) are excluded for size; the setup script can optionally install them to a venv.

---

## Phase 5: Platform-Specific Configuration

### 5.1 Linux (AppImage)
- Already working. Needs Makefile fix and UPX only.
- Verify `.desktop` integration via Tauri's auto-generation.

### 5.2 Windows (MSI)
- Hide console window: `console=False` in PyInstaller spec (conditional)
- Sidecar name: `diarilinux-backend-x86_64-pc-windows-msvc.exe`
- WebView2: pre-installed on Windows 11; add bootstrapper config for Windows 10:
  ```json
  "windows": {
    "webviewInstallMode": { "type": "downloadBootstrapper" },
    "wix": { "language": "en-US" }
  }
  ```

### 5.3 macOS (DMG)
- Build for Apple Silicon (`aarch64-apple-darwin`) — covers M1/M2/M3/M4
- Intel Macs run via Rosetta 2 (transparent to users)
- Sidecar name: `diarilinux-backend-aarch64-apple-darwin`
- Unsigned DMG triggers Gatekeeper warning — document this; code signing is a future step

### 5.4 Tauri config additions

**File:** `desktop/src-tauri/tauri.conf.json`

Add under `bundle`:
```json
"windows": {
  "webviewInstallMode": { "type": "downloadBootstrapper" },
  "wix": { "language": "en-US" }
}
```

---

## Phase 6: Rewrite Makefile

**File:** `desktop/Makefile`

Complete rewrite with platform detection:

```makefile
.PHONY: install build build-frontend build-backend build-sidecar clean

# Platform detection
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)

ifeq ($(UNAME_S),Linux)
    TRIPLE := x86_64-unknown-linux-gnu
    TAURI_TARGETS := appimage,deb
    EXE :=
endif
ifeq ($(UNAME_S),Darwin)
    TRIPLE := $(if $(filter arm64,$(UNAME_M)),aarch64,x86_64)-apple-darwin
    TAURI_TARGETS := dmg
    EXE :=
endif
ifeq ($(OS),Windows_NT)
    TRIPLE := x86_64-pc-windows-msvc
    TAURI_TARGETS := msi
    EXE := .exe
endif

SIDECAR := src-tauri/binaries/diarilinux-backend-$(TRIPLE)$(EXE)

install:
	rustup default stable
	cd ../frontend && npm install
	cd ../backend && uv sync

build-frontend:
	cd ../frontend && npm run build

build-backend:
	cd ../backend && uv run pyinstaller ../desktop/scripts/pyinstaller.spec \
	    --noconfirm --distpath ../desktop/dist --workpath ../desktop/build/pyinstaller

build-sidecar: build-backend
	@mkdir -p src-tauri/binaries
	cp dist/diarilinux-backend$(EXE) $(SIDECAR)
	chmod +x $(SIDECAR)

build: build-frontend build-sidecar
	cd src-tauri && cargo tauri build --target $(TAURI_TARGETS)
	@echo "Packages: src-tauri/target/release/bundle/"

clean:
	rm -rf dist/ build/ src-tauri/target/
```

---

## Phase 7: Rewrite CI Workflow

**File:** `.github/workflows/build.yml`

Remove Android/iOS jobs. Fix all desktop jobs:

```yaml
name: Build & Release
on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - uses: dtolnay/rust-toolchain@stable
      - uses: astral-sh/setup-uv@v4
        with: { enable-cache: true }

      - name: Install system deps
        run: sudo apt-get update && sudo apt-get install -y
          libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev
          librsvg2-dev upx-ucl

      - name: Build frontend
        run: cd frontend && npm ci && npm run build

      - name: Build backend binary
        run: |
          cd backend && uv sync
          uv run pyinstaller ../desktop/scripts/pyinstaller.spec \
            --noconfirm --distpath ../desktop/dist --workpath ../desktop/build/pyinstaller

      - name: Prepare sidecar
        run: |
          mkdir -p desktop/src-tauri/binaries
          cp desktop/dist/diarilinux-backend \
            desktop/src-tauri/binaries/diarilinux-backend-x86_64-unknown-linux-gnu
          chmod +x desktop/src-tauri/binaries/diarilinux-backend-x86_64-unknown-linux-gnu

      - name: Verify backend binary
        run: |
          ./desktop/dist/diarilinux-backend --host 127.0.0.1 --port 18765 &
          PID=$!; sleep 5
          curl -sf http://127.0.0.1:18765/health | grep -q ok
          kill $PID

      - name: Build Tauri (AppImage + deb)
        uses: tauri-apps/tauri-action@v0
        with:
          projectDir: desktop
          tauriScript: cargo tauri

      - uses: actions/upload-artifact@v4
        with:
          name: linux-packages
          path: desktop/src-tauri/target/release/bundle/

  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - uses: dtolnay/rust-toolchain@stable
      - uses: astral-sh/setup-uv@v4
        with: { enable-cache: true }

      - name: Install UPX
        run: choco install upx

      - name: Build frontend
        run: cd frontend && npm ci && npm run build

      - name: Build backend binary
        run: |
          cd backend && uv sync
          uv run pyinstaller ../desktop/scripts/pyinstaller.spec --noconfirm --distpath ../desktop/dist --workpath ../desktop/build/pyinstaller

      - name: Prepare sidecar
        run: |
          mkdir desktop\src-tauri\binaries
          copy desktop\dist\diarilinux-backend.exe desktop\src-tauri\binaries\diarilinux-backend-x86_64-pc-windows-msvc.exe

      - name: Build Tauri (MSI)
        uses: tauri-apps/tauri-action@v0
        with:
          projectDir: desktop
          tauriScript: cargo tauri

      - uses: actions/upload-artifact@v4
        with:
          name: windows-packages
          path: desktop/src-tauri/target/release/bundle/

  build-mac:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - uses: dtolnay/rust-toolchain@stable
      - uses: astral-sh/setup-uv@v4
        with: { enable-cache: true }

      - name: Install UPX
        run: brew install upx

      - name: Build frontend
        run: cd frontend && npm ci && npm run build

      - name: Build backend binary
        run: |
          cd backend && uv sync
          uv run pyinstaller ../desktop/scripts/pyinstaller.spec --noconfirm --distpath ../desktop/dist --workpath ../desktop/build/pyinstaller

      - name: Prepare sidecar
        run: |
          mkdir -p desktop/src-tauri/binaries
          cp desktop/dist/diarilinux-backend \
            desktop/src-tauri/binaries/diarilinux-backend-aarch64-apple-darwin
          chmod +x desktop/src-tauri/binaries/diarilinux-backend-aarch64-apple-darwin

      - name: Build Tauri (DMG)
        uses: tauri-apps/tauri-action@v0
        with:
          projectDir: desktop
          tauriScript: cargo tauri

      - uses: actions/upload-artifact@v4
        with:
          name: macos-packages
          path: desktop/src-tauri/target/release/bundle/
```

---

## Phase 8: Verification

### Automated (CI)
- Backend binary health check on each platform
- `curl http://127.0.0.1:18765/health` returns `{"status": "ok"}`

### Manual smoke tests (all platforms)
1. App launches, window appears (1200x800)
2. Create, edit, delete an entry
3. Upload media (image)
4. Full-text search works
5. Tags and templates CRUD
6. Close and reopen — data persists
7. TTS works (tests `edge_tts` lazy import)
8. AI grammar check works if Ollama is running (tests `httpx` lazy import)

### Graceful degradation
- `faster_whisper` and `weasyprint` are **excluded** from the bundle but lazily imported
- `recording_service.py` already catches ImportError → `RuntimeError("Speech-to-text unavailable")`
- `export_service.py` — verify weasyprint ImportError is caught gracefully
- OCR — requires system tesseract; bundle includes PIL+pytesseract but system must have `tesseract-ocr` installed

---

## Implementation Order

| Step | File | Action |
|------|------|--------|
| 1 | System | Install UPX (`sudo apt install upx-ucl`) |
| 2 | `desktop/scripts/pyinstaller.spec` | Use `collect_submodules('app')`, add stdlib excludes, conditional console |
| 3 | `desktop/src-tauri/Cargo.toml` | Add `[profile.release]` with LTO + size opt |
| 4 | `desktop/scripts/setup-linux.sh` | Create first-run setup script (tesseract, Ollama, system deps) |
| 5 | `desktop/src-tauri/src/main.rs` | Add `run_setup` and `check_deps` Tauri commands |
| 6 | `desktop/src-tauri/tauri.conf.json` | Add resources for setup script, Windows WebView2 config |
| 7 | `frontend/src/components/settings/SettingsView.vue` | Add System Setup section with dep check + run button |
| 8 | `desktop/Makefile` | Rewrite with platform detection, `uv run`, correct sidecar naming |
| 9 | `desktop/` | Rebuild Linux AppImage — verify size reduction + all features |
| 10 | `.github/workflows/build.yml` | Rewrite with `uv`, UPX, sidecar prep, remove mobile jobs |
| 11 | CI | Push tag, verify all 3 platform builds succeed |

---

## Files Summary

| Action | File |
|--------|------|
| Modify | `desktop/scripts/pyinstaller.spec` — auto-discover imports, stdlib excludes, conditional console |
| Modify | `desktop/src-tauri/Cargo.toml` — add release profile for size optimization |
| Modify | `desktop/src-tauri/tauri.conf.json` — add resources, Windows WebView2 config |
| Modify | `desktop/src-tauri/src/main.rs` — add `run_setup` + `check_deps` Tauri commands |
| Modify | `frontend/src/components/settings/SettingsView.vue` — System Setup section |
| Create | `desktop/scripts/setup-linux.sh` — first-run system dep installer |
| Rewrite | `desktop/Makefile` — platform detection, uv run, correct sidecar naming |
| Rewrite | `.github/workflows/build.yml` — uv, UPX, sidecar prep, desktop only |

## Risks

| Risk | Mitigation |
|------|------------|
| UPX breaks Python binary | Test thoroughly; disable UPX if issues arise |
| PyInstaller misses imports on Win/Mac | `collect_submodules('app')` auto-discovers all |
| macOS unsigned DMG | Gatekeeper warning expected; code signing is future work |
| WebView2 missing on Windows 10 | Bootstrapper config in tauri.conf.json |
| `faster_whisper`/`weasyprint` excluded | Lazy imports + graceful error messages |
