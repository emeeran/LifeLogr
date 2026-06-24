#!/usr/bin/env bash
# Build a .deb package for the LifeLogr web version (no Tauri desktop app).
# The backend serves both the API and frontend static files on port 8000.
#
# Usage: ./scripts/build-web-deb.sh
# Output: dist/lifelogr-web_0.1.0_amd64.deb

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(grep '^version' "$ROOT/backend/pyproject.toml" | head -1 | sed 's/.*=.*\"\(.*\)\".*/\1/')"
VERSION="${VERSION:-0.1.0}"
ARCH="amd64"
PKG_NAME="lifelogr-web"
STAGE="$ROOT/dist/deb-stage"
INSTALL_DIR="/opt/lifelogr"

echo "=== Building ${PKG_NAME}_${VERSION}_${ARCH}.deb ==="

# ── Prerequisite checks ────────────────────────────────────────────────────
need_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo "ERROR: '$1' is required. $2"
    exit 1
  fi
}
need_cmd npm "Install Node.js: https://nodejs.org"
need_cmd uv "Install uv: https://docs.astral.sh/uv/"
need_cmd dpkg-deb "Install dpkg: apt install dpkg"

# ── Clean previous build ──────────────────────────────────────────────────
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE$INSTALL_DIR"

# ── 1. Build frontend ─────────────────────────────────────────────────────
echo "[1/4] Building frontend..."
cd "$ROOT/frontend"
npm ci --quiet
npm run build
echo "  → frontend/dist/ ($(du -sh dist/ | cut -f1))"

# ── 2. Create Python venv with production deps ────────────────────────────
echo "[2/4] Creating production venv..."
cd "$ROOT/backend"
# Use system Python so venv works on any target machine
SYSTEM_PYTHON="$(which python3)"
echo "  Using system Python: $SYSTEM_PYTHON ($(python3 --version))"
rm -rf .venv  # Clean any existing venv
uv venv --python "$SYSTEM_PYTHON" .venv --quiet 2>/dev/null || true
uv sync --frozen --no-dev --python "$SYSTEM_PYTHON" --quiet
# Ensure venv python points to system python, not uv cache
ln -sf "$SYSTEM_PYTHON" .venv/bin/python 2>/dev/null || true
ln -sf "$SYSTEM_PYTHON" .venv/bin/python3 2>/dev/null || true
echo "  → backend/.venv/ ($(du -sh .venv/ | cut -f1))"

# ── 3. Assemble package files ─────────────────────────────────────────────
echo "[3/4] Assembling package..."

# Backend code + venv
mkdir -p "$STAGE$INSTALL_DIR/backend"
cp -r "$ROOT/backend/app"       "$STAGE$INSTALL_DIR/backend/"
cp -r "$ROOT/backend/.venv"     "$STAGE$INSTALL_DIR/backend/"
cp "$ROOT/backend/pyproject.toml" "$STAGE$INSTALL_DIR/backend/"
cp "$ROOT/backend/.python-version" "$STAGE$INSTALL_DIR/backend/" 2>/dev/null || true

# Built frontend
mkdir -p "$STAGE$INSTALL_DIR/frontend"
cp -r "$ROOT/frontend/dist"     "$STAGE$INSTALL_DIR/frontend/"

# Assets
cp -r "$ROOT/assets"            "$STAGE$INSTALL_DIR/"

# Data directory for DB + media
mkdir -p "$STAGE/var/lib/lifelogr"
mkdir -p "$STAGE/var/lib/lifelogr/media"

# Config directory
mkdir -p "$STAGE/etc/lifelogr"

# Create default .env with auto-generated SECRET_KEY
GENERATED_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
cat > "$STAGE/etc/lifelogr/.env" << ENVEOF
APP_ENV=production
DATABASE_URL=sqlite+aiosqlite:////var/lib/lifelogr/lifelogr.db
MEDIA_DIR=/var/lib/lifelogr/media
DATA_DIR=/var/lib/lifelogr
SECRET_KEY=${GENERATED_SECRET}
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
ENVEOF

# Systemd service
mkdir -p "$STAGE/etc/systemd/system"
cat > "$STAGE/etc/systemd/system/lifelogr.service" << 'SVCEOF'
[Unit]
Description=LifeLogr Journal (Web)
After=network.target

[Service]
Type=simple
User=lifelogr
Group=lifelogr
WorkingDirectory=/opt/lifelogr/backend
EnvironmentFile=/etc/lifelogr/.env
ExecStart=/opt/lifelogr/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/lifelogr
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SVCEOF

# Nginx reverse proxy config (optional — serves on port 80)
mkdir -p "$STAGE/etc/nginx/sites-available"
cat > "$STAGE/etc/nginx/sites-available/lifelogr" << 'NGXEOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
NGXEOF

# ── 4. Create DEBIAN control files ────────────────────────────────────────

# control
cat > "$STAGE/DEBIAN/control" << EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: Meeran <me@lifelogr.dev>
Depends: python3, python3-venv, libpango-1.0-0, libpangocairo-1.0-0, libgdk-pixbuf2.0-0, libffi-dev, libcairo2, shared-mime-info, tesseract-ocr
Recommends: nginx, ollama
Section: web
Priority: optional
Description: LifeLogr — Privacy-first journaling web app
 FastAPI backend + Vue 3 frontend served as a single web application.
 Includes AI-assisted features via Ollama, encryption, markdown editing,
 media attachments, and voice recording with transcription.
Homepage: https://github.com/lifelogr/lifelogr
EOF

# postinst — create user, set permissions, enable service
cat > "$STAGE/DEBIAN/postinst" << 'POSTEOF'
#!/bin/bash
set -e

# Create service user if it doesn't exist
if ! id -u lifelogr &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin lifelogr
fi

# Set ownership
chown -R lifelogr:lifelogr /var/lib/lifelogr
chown -R lifelogr:lifelogr /opt/lifelogr

# Make venv relocatable — fix shebangs to match install location
INSTALL_DIR="/opt/lifelogr/backend"
# Fix any absolute paths in venv bin scripts to point to install location
find /opt/lifelogr/backend/.venv/bin -type f -exec sed -i "s|^#!.*python|#!/usr/bin/python3|g" {} + 2>/dev/null || true
# Update pyvenv.cfg to point to system python
sed -i "s|^home = .*|home = /usr/bin|g" /opt/lifelogr/backend/.venv/pyvenv.cfg 2>/dev/null || true

# Enable and start service
systemctl daemon-reload
systemctl enable lifelogr
systemctl restart lifelogr

# Optionally enable nginx site
if [ -d /etc/nginx/sites-enabled ] && [ -f /etc/nginx/sites-available/lifelogr ]; then
    ln -sf /etc/nginx/sites-available/lifelogr /etc/nginx/sites-enabled/lifelogr
    nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
fi

echo ""
echo "LifeLogr web app installed!"
echo "  - Service:  systemctl status lifelogr"
echo "  - Config:   /etc/lifelogr/.env"
echo "  - Data:     /var/lib/lifelogr/"
echo "  - Logs:     journalctl -u lifelogr -f"
echo ""
echo "Edit /etc/lifelogr/.env to set SECRET_KEY, then:"
echo "  sudo systemctl restart lifelogr"
echo ""
POSTEOF
chmod 755 "$STAGE/DEBIAN/postinst"

# prerm — stop service
cat > "$STAGE/DEBIAN/prerm" << 'PREEOF'
#!/bin/bash
set -e
systemctl stop lifelogr 2>/dev/null || true
systemctl disable lifelogr 2>/dev/null || true
PREEOF
chmod 755 "$STAGE/DEBIAN/prerm"

# postrm — clean up (only on purge)
cat > "$STAGE/DEBIAN/postrm" << 'POSTEOF'
#!/bin/bash
set -e
if [ "$1" = "purge" ]; then
    rm -rf /var/lib/lifelogr
    rm -f /etc/nginx/sites-enabled/lifelogr
    userdel lifelogr 2>/dev/null || true
fi
POSTEOF
chmod 755 "$STAGE/DEBIAN/postrm"

# ── 5. Build the .deb ─────────────────────────────────────────────────────
echo "[4/4] Building .deb package..."
mkdir -p "$ROOT/dist"
dpkg-deb --build "$STAGE" "$ROOT/dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"

DEB_SIZE=$(du -sh "$ROOT/dist/${PKG_NAME}_${VERSION}_${ARCH}.deb" | cut -f1)
echo ""
echo "=== Done: dist/${PKG_NAME}_${VERSION}_${ARCH}.deb ($DEB_SIZE) ==="
echo ""
echo "Install:  sudo dpkg -i dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"
echo "Remove:   sudo dpkg -r ${PKG_NAME}"
echo "Purge:    sudo dpkg --purge ${PKG_NAME}"
