# LifeLogr — Deployment & Packaging Guide

> How to build, deploy, and package LifeLogr for all platforms.

---

## Table of Contents

1. [Development Setup](#1-development-setup)
2. [Building for Production](#2-building-for-production)
3. [Docker Deployment](#3-docker-deployment)
4. [systemd Service](#4-systemd-service)
5. [Desktop Packaging (Tauri)](#5-desktop-packaging-tauri)
6. [CI/CD Pipeline](#6-cicd-pipeline)
7. [Environment Variables](#7-environment-variables)
8. [Data Storage](#8-data-storage)
9. [Security Considerations](#9-security-considerations)

---

## 1. Development Setup

### Prerequisites

- **Python 3.11+** with `uv` package manager
- **Node.js 20+** with npm
- **Rust** (for Tauri desktop builds)
- **Git**

### Quick Start

```bash
# Clone the repo
git clone https://github.com/your-org/lifelogr.git
cd lifelogr

# Install backend dependencies
cd backend
uv sync

# Install frontend dependencies
cd ../frontend
npm install

# Launch both servers (auto-picks available ports)
cd ..
chmod +x dev.sh
./dev.sh
```

### Manual Start

```bash
# Terminal 1: Backend
cd backend
uv run uvicorn app.main:app --port 8000 --reload

# Terminal 2: Frontend
cd frontend
npm run dev
```

The frontend dev server proxies API requests to the backend via Vite's proxy config.

---

## 2. Building for Production

### Frontend Build

```bash
cd frontend
npm run build
```

Output: `frontend/dist/` — static HTML/CSS/JS files ready to serve.

### Backend Build

The backend runs directly from source in production:

```bash
cd backend
APP_ENV=production uv run uvicorn app.main:app --host 127.0.0.1 --port 18765
```

> Production runs **refuse to start** bound to a non-loopback address unless
> `LIFELOGR_IN_CONTAINER=1` is set (the Docker image's documented exception).
> For remote access, bind to loopback and terminate at an authenticated reverse
> proxy.

For packaged desktop apps, the backend is bundled into a single binary via PyInstaller (see Section 5).

### Production Static File Serving

When `APP_ENV=production`, the FastAPI backend serves the built frontend from `frontend/dist/` automatically. Only the backend needs to be deployed.

---

## 3. Docker Deployment

### Dockerfile

The project includes a multi-stage Dockerfile:

```bash
# Build the image
docker build -t lifelogr .

# Run the container
docker run -d \
  -p 127.0.0.1:8000:8000 \
  -v lifelogr-data:/app/backend/data \
  --name lifelogr \
  lifelogr
```

The image has a **single volume** `/app/backend/data` (`DATA_DIR` points there):
the database, media and TTS cache all live under it.

### Docker Compose

```bash
# Start
docker compose up -d

# Stop
docker compose down

# View logs
docker compose logs -f

# Rebuild after changes
docker compose up -d --build
```

**docker-compose.yml configuration:**

```yaml
services:
  app:
    build: .
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - ./data:/app/backend/data
    environment:
      - APP_ENV=production
      - DATA_DIR=/app/backend/data
      - DATABASE_URL=
    env_file:
      - backend/.env
      # required: false — the container never runs on the public default
      # SECRET_KEY: for managed runs a stable key is auto-generated into
      # ./data/.secret_key unless the env file sets one.
    restart: unless-stopped
```

### Environment File (optional)

Create `backend/.env` to override defaults:

```env
SECRET_KEY=your-random-secret-key-here
CORS_ORIGINS=http://your-domain.com
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

---

## 4. systemd Service

For running as a system service on Linux:

### Service File

> The packaged web `.deb` does **not** install a systemd service — it ships a
> per-user, on-demand launcher (`lifelogr` / `lifelogr --stop`). The unit below
> is for manual server setups only.

Create a service file:

```ini
[Unit]
Description=LifeLogr Journal App
After=network.target

[Service]
Type=simple
User=lifelogr
WorkingDirectory=/opt/lifelogr
ExecStart=/opt/lifelogr/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18765
Environment=APP_ENV=production
Environment=SECRET_KEY=your-secret-key
Environment=DATA_DIR=/var/lib/lifelogr
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Installation

```bash
# Copy service file (or use the one from build output)
sudo cp lifelogr.service /etc/systemd/system/

# Create data directory
sudo mkdir -p /var/lib/lifelogr/media
sudo chown lifelogr:lifelogr /var/lib/lifelogr

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable lifelogr
sudo systemctl start lifelogr

# Check status
sudo systemctl status lifelogr

# View logs
sudo journalctl -u lifelogr -f
```

### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name diary.example.com;

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Long timeout for AI operations
        proxy_read_timeout 300s;
    }
}
```

---

## 5. Desktop Packaging (Tauri)

### Architecture

```
┌──────────────────────────────────────┐
│  Tauri Native Shell (Rust)           │
│  ┌────────────────────────────────┐  │
│  │  WebView (Vue.js Frontend)     │  │
│  └────────────────────────────────┘  │
│  + Sidecar: PyInstaller Backend      │
│  + Single Instance Lock              │
│  + Platform Data Directory           │
└──────────────────────────────────────┘
```

### Prerequisites

- **Rust** stable toolchain: `rustup default stable`
- **Tauri CLI**: `cargo install tauri-cli`
- **PyInstaller**: `pip install pyinstaller`
- **System libraries** (Linux only):
  ```bash
  sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
  ```

### Building

#### Linux (AppImage + DEB)

Linux is the only packaging target (Windows/macOS were removed in 0.16.0):

```bash
cd desktop
make build
```

Output:
- `desktop/src-tauri/target/release/bundle/appimage/` — AppImage
- `desktop/src-tauri/target/release/bundle/deb/` — Debian package

### Build Steps Explained

1. **Frontend build**: `npm run build` → `frontend/dist/`
2. **Backend binary**: PyInstaller bundles `backend/` into `lifelogr-backend`
3. **Sidecar placement**: Binary copied to `src-tauri/binaries/` with platform suffix
4. **Tauri build**: Rust compiles the native shell, bundles frontend + sidecar

### Data Directory

The Tauri shell passes `DATA_DIR` to the backend sidecar:

| Platform | Path |
|----------|------|
| Linux | `~/.local/share/com.lifelogr.desktop/` |

### PyInstaller Spec

The backend is bundled using `desktop/scripts/pyinstaller.spec`:

- Includes all required Python packages
- Excludes heavy unused dependencies (torch, scipy, matplotlib, weasyprint, mega) for a smaller bundle
- Pillow is dieted to the image formats LifeLogr accepts (PNG/JPEG/WebP/BMP/TIFF/GIF/MPO); `ImageCms`/`ImageFont` are excluded so freetype/littlecms leave the bundle
- Produces a single executable with no Python installation required
- Stripped (`strip=True`, `upx=False` — UPX is not used)

---

## 6. CI/CD Pipeline

### GitHub Actions

Two workflows:

- **`ci.yml`** — the merge gate: backend lint/type/tests (coverage ≥ 78 %), frontend typecheck/unit/build, Playwright e2e, version parity across the five sources, `cargo check` on the Rust shell.
- **`build.yml`** — release artifacts. Its `tests` job calls `ci.yml` as a reusable workflow, so **a tag can't produce installers unless the full gate is green**.

**Triggers:**
- Push a version tag: `git tag v1.0.0 && git push --tags`
- Manual dispatch via GitHub Actions UI

**Jobs:**

| Job | Runner | Output |
|-----|--------|--------|
| `tests` | ubuntu-latest | Runs the `ci.yml` gate |
| `build-linux` | ubuntu-24.04 | AppImage + .deb + `checksums.txt` (sha256) |

Artifacts are uploaded to the GitHub release.

### Manual Build

From `desktop/`, the Makefile drives the same pipeline CI uses (frontend build,
PyInstaller sidecar, Tauri bundle):

```bash
cd desktop && make build    # AppImage + .deb into src-tauri/target/release/bundle/
```

### Release Workflow

```bash
# 1. Update version (all five sources at once)
#   make bump V=x.y.z

# 2. Commit and tag
git add -A
git commit -m "chore: bump version to vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags

# 3. CI/CD builds and publishes
# Artifacts appear in GitHub Releases
```

---

## 7. Environment Variables

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | `development` or `production` |
| `SECRET_KEY` | `change-me-before-production` | **Must be changed in production** (managed/launcher runs auto-generate a stable key into the data dir) |
| `BIND_HOST` | `127.0.0.1` | Bind address — production refuses non-loopback unless `LIFELOGR_IN_CONTAINER=1` |
| `BIND_PORT` | `18765` | Listen port |
| `API_TOKEN` | unset | When set, every `/api/*` call requires `Authorization: Bearer …` |
| `DATA_DIR` | Platform default | Root data directory |
| `DATABASE_URL` | Derived from DATA_DIR | SQLAlchemy connection string |
| `MEDIA_DIR` | Derived from DATA_DIR | File upload directory |
| `CORS_ORIGINS` | `http://localhost:5173,tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://127.0.0.1:18765` | Comma-separated allowed origins |
| `MAX_MEDIA_SIZE_BYTES` | `26214400` (25 MB) | Max upload file size |

### AI / Ollama

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama service URL |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model to use for AI features |
| `OLLAMA_TIMEOUT_SECONDS` | `300` | Request timeout |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_SIZE` | `5` | SQLite connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Max overflow connections |
| `RATE_LIMIT` | `60/minute` | Rate limit per IP |

### Tauri Sidecar

| Variable | Description |
|----------|-------------|
| `DATA_DIR` | Set by Tauri shell — data directory for the app |

### Frontend Build

| Variable | Description |
|----------|-------------|
| `VITE_BACKEND_PORT` | Backend port for dev server proxy |

---

## 8. Data Storage

### File Structure

```
{DATA_DIR}/
├── lifelogr.db            # SQLite database
├── lifelogr.db.boot-bak-* # rotating boot snapshots (2 recent + weekly)
├── .secret_key            # auto-generated key for managed runs (mode 0600)
├── media/
│   ├── abc123.jpg         # Uploaded media files
│   ├── def456.png
│   └── ...
├── tts/                   # read-aloud audio cache
├── weather/               # cached weather enrichment data
└── backups/               # scheduled local backups
```

The data directory can be relocated via the storage-override file
`$XDG_CONFIG_HOME/lifelogr/data-location.json` (Settings → Data → Storage
location); it lives outside `DATA_DIR` on purpose so it survives relocation.

### Platform Defaults

| Platform | DATA_DIR |
|----------|----------|
| Linux (Tauri desktop) | `~/.local/share/com.lifelogr.desktop/` |
| Linux (web/dev, unset DATA_DIR) | `~/.local/share/lifelogr/` |
| Docker | `/app/backend/data` (volume-mounted) |

### Database

- **Engine:** SQLite with aiosqlite (async) — there is no PostgreSQL path; `DATABASE_URL` is always derived from `DATA_DIR`
- **Location:** `{DATA_DIR}/lifelogr.db`
- **WAL mode:** Enabled automatically — allows concurrent reads during writes
- **Foreign keys:** Enforced (`PRAGMA foreign_keys=ON`) — cascading deletes active
- **Busy timeout:** 10 seconds — prevents immediate "database is locked" errors
- **Connection pool:** `pool_size=DB_POOL_SIZE` (default 5) + `max_overflow=DB_MAX_OVERFLOW` (default 10)
- **Boot integrity:** `PRAGMA quick_check` at boot (full `integrity_check` on failure + weekly Sundays 04:00), with automatic recovery from the newest intact boot snapshot
- **FTS:** Full-text search via FTS5 virtual tables (`entries_fts`, `notes_fts`), auto-rebuilt on startup if stale
- **Migrations:** Auto-creates tables on startup (`Base.metadata.create_all`) + lightweight column migrations via `_COLUMN_MIGRATIONS`
- **Backup:** WAL checkpoint before export; atomic restore with rollback on failure

### Media Storage

- Uploaded files stored in `{DATA_DIR}/media/`
- File names are UUIDs to prevent collisions
- Original filename preserved in database metadata
- MIME type validated on upload (magic number check)
- Blocked file types: executables, scripts, HTML

---

## 9. Security Considerations

### Production Checklist

- [ ] Change `SECRET_KEY` from default value
- [ ] Set `APP_ENV=production` (disables `/docs`, restricts CORS)
- [ ] Configure `CORS_ORIGINS` to your actual domain
- [ ] Use HTTPS via reverse proxy (Nginx, Caddy)
- [ ] Set up rate limiting (built-in at 60/min, or proxy-level)
- [ ] Restrict file upload sizes (`MAX_MEDIA_SIZE_BYTES`)
- [ ] Regular database backups
- [ ] Run as non-root user (systemd, Docker)

### Built-in Security

| Feature | Implementation |
|---------|---------------|
| CORS | Configurable origins, credentials supported |
| Rate Limiting | In-memory per-IP, 60 req/min with memory leak protection |
| File Validation | Magic number check, MIME whitelist |
| Blocked Files | Executables, scripts, HTML blocked |
| Path Traversal | `..` sequences rejected in filenames |
| Archive Safety | Tar members validated before extraction (path traversal blocked) |
| Model Validation | Ollama model names validated before subprocess execution |
| XSS | DOMPurify sanitization on rendered HTML |
| Encryption | AES-256-GCM for entry-level encryption |
| Backup Atomicity | Restore backs up current DB first, rolls back on failure |
| Request Logging | UUID-based tracking with timing |
| Health Check | `/health` verifies database connectivity |
| Graceful Shutdown | Engine disposed, background enrichment tasks cancelled |

### Docker Security

```yaml
# Run as non-root user
services:
  app:
    user: "1000:1000"
    read_only: true
    tmpfs:
      - /tmp
    volumes:
      - ./data:/app/backend/data
```

### Reverse Proxy Headers

When behind a reverse proxy, ensure these headers are forwarded:

```
X-Real-IP
X-Forwarded-For
X-Forwarded-Proto
```

This ensures correct rate limiting and URL generation.
