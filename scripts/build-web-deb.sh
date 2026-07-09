#!/usr/bin/env bash
# Build a .deb package for the LifeLogr web app (no Tauri desktop shell).
#
# RUNTIME MODEL: on-demand desktop launcher.
#   - A .desktop entry ("LifeLogr") runs /opt/lifelogr/bin/lifelogr.
#   - The launcher picks a FREE port (avoids clashes with other local apps),
#     starts uvicorn detached AS THE DESKTOP USER, opens the browser, and
#     records pid+port to ~/.local/share/lifelogr/runtime for single-instance /
#     `lifelogr --stop`.
#   - No systemd service, no system user, no /var/lib. Per-user data lives in
#     ~/.local/share/lifelogr (the app's own default DATA_DIR), so it runs
#     without root and reuses existing journal data.
#
# PORTABILITY: the Python venv is created on the TARGET at install time (needs
# network) using a bundled `uv` + a locked requirements.txt with environment
# markers, so it works on any python3 >= 3.11 / amd64 Linux.
#
# Package layout:
#   /opt/lifelogr/bin/uv                 bundled uv (creates the venv)
#   /opt/lifelogr/bin/lifelogr-setup     venv-build helper (re-runnable)
#   /opt/lifelogr/bin/lifelogr           desktop launcher (free port + browser)
#   /opt/lifelogr/backend/{app,requirements.txt,uv.lock,pyproject.toml}
#   /opt/lifelogr/frontend/dist          built SPA (served as static files)
#   /opt/lifelogr/assets                 logos
#   /usr/share/applications/LifeLogr.desktop      app-menu entry
#   /usr/share/applications/LifeLogr-stop.desktop stop entry
#
# Usage: ./scripts/build-web-deb.sh
# Output: dist/lifelogr-web_<version>_amd64.deb

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(grep '^version' "$ROOT/backend/pyproject.toml" | head -1 | sed 's/.*=.*\"\(.*\)\".*/\1/')"
VERSION="${VERSION:-0.1.0}"
ARCH="amd64"
PKG_NAME="lifelogr-web"
STAGE="$ROOT/dist/deb-stage"
INSTALL_DIR="/opt/lifelogr"

echo "=== Building ${PKG_NAME}_${VERSION}_${ARCH}.deb (on-demand launcher) ==="

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
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE$INSTALL_DIR/bin" \
         "$STAGE$INSTALL_DIR/backend" \
         "$STAGE$INSTALL_DIR/frontend" \
         "$STAGE$INSTALL_DIR/assets" \
         "$STAGE/usr/share/applications"

# ── 1. Build frontend ─────────────────────────────────────────────────────
echo "[1/4] Building frontend..."
cd "$ROOT/frontend"
npm ci --quiet
# Inject the version at build time so the About tab matches the bundle without
# waiting on a backend /settings round-trip (see frontend/src/version.ts).
VITE_APP_VERSION="$VERSION" npm run build
echo "  → frontend/dist/ ($(du -sh dist/ | cut -f1))"

# ── 2. Export locked requirements + stage the bundled uv binary ───────────
echo "[2/4] Exporting locked requirements + staging uv..."
cd "$ROOT/backend"
uv export --frozen --no-dev --no-emit-project --no-hashes \
  --format requirements-txt -o "$STAGE$INSTALL_DIR/backend/requirements.txt"
echo "  → $(wc -l < "$STAGE$INSTALL_DIR/backend/requirements.txt") pinned requirements"
cp "$(command -v uv)" "$STAGE$INSTALL_DIR/bin/uv"
chmod 755 "$STAGE$INSTALL_DIR/bin/uv"
echo "  → bundled uv $(uv --version 2>&1) ($(du -h "$STAGE$INSTALL_DIR/bin/uv" | cut -f1))"

# ── 3. Assemble package files ─────────────────────────────────────────────
echo "[3/4] Assembling package..."

# Backend source (the venv is created at install time — NOT shipped)
cp -r "$ROOT/backend/app"            "$STAGE$INSTALL_DIR/backend/"
cp    "$ROOT/backend/pyproject.toml" "$STAGE$INSTALL_DIR/backend/"
cp    "$ROOT/backend/uv.lock"        "$STAGE$INSTALL_DIR/backend/"

# Built frontend (copy the dist/ dir itself — main.py serves frontend/dist) + assets
cp -r "$ROOT/frontend/dist"          "$STAGE$INSTALL_DIR/frontend/"
cp -r "$ROOT/assets/."               "$STAGE$INSTALL_DIR/assets/"

# ── venv-build helper (re-runnable; called by postinst) ───────────────────
cat > "$STAGE$INSTALL_DIR/bin/lifelogr-setup" << 'SETUPEOF'
#!/bin/bash
# Create/refresh the LifeLogr virtualenv on the TARGET using its own python3.
# Idempotent: safe to re-run after a failed (e.g. offline) first install.
# Requires network access (downloads wheels from PyPI).
set -euo pipefail

INSTALL_DIR=/opt/lifelogr
BACKEND="$INSTALL_DIR/backend"
UV="$INSTALL_DIR/bin/uv"
VENV="$BACKEND/.venv"
REQS="$BACKEND/requirements.txt"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "ERROR: python3 not found on PATH. Install python3 (>= 3.11)." >&2
    exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "ERROR: LifeLogr requires Python >= 3.11; found $("$PY" --version 2>&1)." >&2
    exit 1
fi

echo "→ Creating venv with $("$PY" --version 2>&1) ..."
# --clear: recreate the venv on every run (upgrades/recovery) so we never land
# on a stale or half-built one. uv errors on an existing venv without it when
# run non-interactively (no TTY to confirm replacement). Wheel cache at
# UV_CACHE_DIR makes the subsequent reinstall fast.
"$UV" venv --python "$PY" --clear "$VENV" >/dev/null

echo "→ Installing dependencies from $REQS (network required) ..."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/var/cache/lifelogr-uv}"
mkdir -p "$UV_CACHE_DIR"
if ! "$UV" pip install --python "$VENV/bin/python" -r "$REQS"; then
    echo "" >&2
    echo "ERROR: dependency installation failed — likely no network access." >&2
    echo "       Get the machine online, then re-run:" >&2
    echo "         sudo $INSTALL_DIR/bin/lifelogr-setup" >&2
    exit 1
fi

echo "→ Verifying imports ..."
"$VENV/bin/python" -c 'import fastapi, uvicorn, sqlalchemy, aiosqlite' || {
    echo "ERROR: venv import self-check failed at $VENV." >&2
    exit 1
}
echo "✓ LifeLogr venv ready."
SETUPEOF
chmod 755 "$STAGE$INSTALL_DIR/bin/lifelogr-setup"

# ── desktop launcher (free port, single instance, opens browser) ──────────
cat > "$STAGE$INSTALL_DIR/bin/lifelogr" << 'LAUNCHEREOF'
#!/usr/bin/env bash
# LifeLogr desktop launcher.
#   Picks a FREE port, starts the FastAPI server (single instance) as the
#   current desktop user, opens the browser, and records pid+port for
#   `lifelogr --stop`. Data lives in ~/.local/share/lifelogr (the app's own
#   default DATA_DIR). No root required at runtime.
#
# Usage:
#   lifelogr            start (or focus) the app and open the browser
#   lifelogr --stop     stop the running instance
#   lifelogr --status   report running state
set -uo pipefail

INSTALL_DIR=/opt/lifelogr
BACKEND="$INSTALL_DIR/backend"
VENV="$BACKEND/.venv"

# Per-user data dir — mirrors the app's default DATA_DIR (XDG_DATA_HOME/lifelogr).
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DATA_DIR="${LIFELOGR_DATA_DIR:-$XDG_DATA_HOME/lifelogr}"
STATE_FILE="$DATA_DIR/runtime"        # plain text: "<pid> <port>"
LOG_FILE="$DATA_DIR/server.log"
SECRET_FILE="$DATA_DIR/.secret_key"

die() { echo "lifelogr: $*" >&2; exit 1; }

# Ensure the venv exists (e.g. first run after an offline install).
if [ ! -x "$VENV/bin/python" ]; then
    echo "lifelogr: virtualenv missing — building it now (needs network)..."
    if [ "$(id -u)" -ne 0 ]; then
        die "run once as root to build the venv: sudo $INSTALL_DIR/bin/lifelogr-setup"
    fi
    "$INSTALL_DIR/bin/lifelogr-setup" || die "setup failed"
fi
PYTHON="$VENV/bin/python"

mkdir -p "$DATA_DIR/media"

# Persistent SECRET_KEY (generated once, reused so encryption keys stay stable).
if [ -z "${SECRET_KEY:-}" ]; then
    if [ -s "$SECRET_FILE" ]; then
        SECRET_KEY="$(cat "$SECRET_FILE")"
    else
        SECRET_KEY="$("$PYTHON" -c 'import secrets;print(secrets.token_hex(32))')"
        ( umask 077; printf '%s' "$SECRET_KEY" > "$SECRET_FILE" )
    fi
fi
export SECRET_KEY
# APP_ENV left at its default ("development"): rate-limiting is off, which is
# correct for a single-user loopback app (the app's own note says limiting the
# user's own bulk imports/enrichment is harmful).

read_state() {  # echoes "<pid> <port>" or nothing
    [ -f "$STATE_FILE" ] && read -r SPID SPORT < "$STATE_FILE" 2>/dev/null && \
        { [ -n "${SPID:-}" ] && echo "$SPID ${SPORT:-}"; }
    return 0
}

# ── subcommands ──
case "${1:-}" in
    --stop)
        st="$(read_state)"; pid="${st% *}"; port="${st##* }"
        if [ -n "$st" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true; sleep 1; kill -9 "$pid" 2>/dev/null || true
            echo "lifelogr: stopped (was pid $pid, port $port)."
        else
            echo "lifelogr: not running."
        fi
        rm -f "$STATE_FILE"; exit 0 ;;
    --status)
        st="$(read_state)"; pid="${st% *}"; port="${st##* }"
        if [ -n "$st" ] && kill -0 "$pid" 2>/dev/null; then
            echo "lifelogr: running at http://127.0.0.1:$port (pid $pid)."; exit 0
        fi
        echo "lifelogr: not running."; exit 1 ;;
esac

# ── single instance: focus + reopen browser if already running ──
st="$(read_state)"; pid="${st% *}"; port="${st##* }"
if [ -n "$st" ] && kill -0 "$pid" 2>/dev/null; then
    echo "lifelogr: already running at http://127.0.0.1:$port — opening browser."
    xdg-open "http://127.0.0.1:$port" >/dev/null 2>&1 || true
    exit 0
fi
rm -f "$STATE_FILE"   # stale

# ── pick a free port: prefer 18765 — that's the OAuth loopback redirect port
# the backup providers hardcode (Google Drive/Box/OneDrive/Dropbox callbacks),
# and the SPA must be reachable there for "Sign in" to complete. Fall back to
# 8000-8019, then an OS-assigned port, only if 18765 is taken.
PORT="$("$PYTHON" - <<'PY'
import socket
def free(p):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", p)); s.close(); return True
    except OSError:
        s.close(); return False
for p in (18765, *range(8000, 8020)):
    if free(p):
        print(p); break
else:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1]); s.close()
PY
)"
[ -n "$PORT" ] || die "could not allocate a free port"

echo "lifelogr: starting on http://127.0.0.1:$PORT ..."
cd "$BACKEND"
nohup "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --no-access-log \
    >> "$LOG_FILE" 2>&1 &
UVPID=$!

# Wait for readiness (first launch creates the DB; allow up to ~30s).
"$PYTHON" - "$PORT" "$UVPID" <<'PY'
import os, sys, time, urllib.request
port, pid = sys.argv[1], int(sys.argv[2])
url = f"http://127.0.0.1:{port}/health"
for _ in range(60):
    try:
        urllib.request.urlopen(url, timeout=1)
        sys.exit(0)   # ready
    except Exception:
        pass
    try:
        os.kill(pid, 0)           # bail early if the server process died
    except OSError:
        sys.exit(2)
    time.sleep(0.5)
sys.exit(1)   # never became ready
PY
case $? in
    0) ;;  # ready
    2) rm -f "$STATE_FILE"; die "server exited unexpectedly — see $LOG_FILE" ;;
    *) rm -f "$STATE_FILE"; die "server did not become ready — see $LOG_FILE" ;;
esac

# Record pid+port (plain text), then open the browser.
echo "$UVPID $PORT" > "$STATE_FILE"
xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true
echo "lifelogr: ready at http://127.0.0.1:$PORT (pid $UVPID)."
echo "          stop with: lifelogr --stop   ·   data: $DATA_DIR"
LAUNCHEREOF
chmod 755 "$STAGE$INSTALL_DIR/bin/lifelogr"

# Expose the launcher as the `lifelogr` shell command (on PATH via /usr/local/bin).
mkdir -p "$STAGE/usr/local/bin"
ln -s "$INSTALL_DIR/bin/lifelogr" "$STAGE/usr/local/bin/lifelogr"

# ── .desktop entries ──────────────────────────────────────────────────────
cat > "$STAGE/usr/share/applications/LifeLogr.desktop" << EOF
[Desktop Entry]
Type=Application
Version=1.5
Name=LifeLogr
GenericName=Journal
Comment=Privacy-first journaling (web)
Comment[en_US]=Privacy-first journaling (web)
Exec=$INSTALL_DIR/bin/lifelogr
Icon=$INSTALL_DIR/assets/lifelogr-logo.png
Terminal=false
Categories=Office;Utility;Journal;
Keywords=journal;diary;notes;memoir;
StartupNotify=true
StartupWMClass=LifeLogr
EOF

cat > "$STAGE/usr/share/applications/LifeLogr-stop.desktop" << EOF
[Desktop Entry]
Type=Application
Name=LifeLogr — Stop
Comment=Stop the running LifeLogr server
Comment[en_US]=Stop the running LifeLogr server
Exec=$INSTALL_DIR/bin/lifelogr --stop
Icon=$INSTALL_DIR/assets/lifelogr-logo.png
Terminal=false
Categories=Office;Utility;
NoDisplay=true
EOF

# ── 4. DEBIAN control files ───────────────────────────────────────────────

cat > "$STAGE/DEBIAN/control" << EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: Meeran <me@lifelogr.dev>
Depends: python3 (>= 3.11), shared-mime-info, tesseract-ocr
Recommends: ollama
Section: web
Priority: optional
Description: LifeLogr — Privacy-first journaling web app
 Launched from the desktop menu on a free port; runs as your user with
 data in ~/.local/share/lifelogr. The Python venv is built on the target
 at install time (needs network), so it runs on any Python 3.11+ / amd64
 Linux. Includes AI-assisted features via Ollama, encryption, markdown
 editing, media attachments, and voice recording.
Homepage: https://github.com/lifelogr/lifelogr
EOF

# preinst — stop any running per-user instance BEFORE unpack/rebuild, so the
# postinst venv rebuild can't corrupt a live process or leave a stale one.
# Runs as root; instances are per-user (no systemd), so we scan every home for
# its runtime file (~/.local/share/lifelogr/runtime = "<pid> <port>") and stop
# those pids, then pkill any uvicorn serving /opt/lifelogr as a fallback.
cat > "$STAGE/DEBIAN/preinst" << 'PREEOF'
#!/bin/bash
# Stop running LifeLogr instances before install/upgrade. The app runs as a
# per-user process (not root, no systemd service), so we locate each user's
# runtime file and stop those pids, then pkill any uvicorn serving
# /opt/lifelogr as a fallback.
set -e

stop_pid() {
    pid="$1"; rt="${2:-}"
    [ -n "${pid:-}" ] || return 0
    # Only kill if it's genuinely a LifeLogr uvicorn process — guards against
    # the pid having been recycled to an unrelated process after a stop.
    if kill -0 "$pid" 2>/dev/null \
       && grep -qa "app.main:app" /proc/"$pid"/cmdline 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        # Give it a moment to flush the SQLite WAL, then force if needed.
        for _ in 1 2 3 4 5; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.2
        done
        kill -9 "$pid" 2>/dev/null || true
    fi
    [ -n "$rt" ] && rm -f "$rt"
}

# Scan every user home (incl. root) for a runtime file.
for rt in /home/*/.local/share/lifelogr/runtime \
          /root/.local/share/lifelogr/runtime \
          "${HOME:-}/.local/share/lifelogr/runtime"; do
    [ -f "$rt" ] || continue
    pid=""; port=""
    { read -r pid port || true; } < "$rt"
    stop_pid "$pid" "$rt"
done

# Fallback: catch an instance whose runtime file we couldn't find.
# (pkill never signals itself, so this is safe to run.)
pkill -f "/opt/lifelogr/backend/.venv/bin/python -m uvicorn app.main:app" 2>/dev/null || true

exit 0
PREEOF
chmod 755 "$STAGE/DEBIAN/preinst"

# postinst — build the venv on this machine + register the desktop entries.
cat > "$STAGE/DEBIAN/postinst" << 'POSTEOF'
#!/bin/bash
set -e

# Build the venv on THIS machine (portable: native python + matching wheels).
# Needs network. On failure we exit non-zero; the user can re-run:
#   sudo /opt/lifelogr/bin/lifelogr-setup
if ! /opt/lifelogr/bin/lifelogr-setup; then
    echo "" >&2
    echo "LifeLogr setup did not complete (network issue?)." >&2
    echo "Re-run once online:  sudo /opt/lifelogr/bin/lifelogr-setup" >&2
    exit 1
fi

# Make the app-menu entry discoverable.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi

echo ""
echo "LifeLogr installed!"
echo "  - Launch:    'LifeLogr' in your app menu, or run:  lifelogr"
echo "  - Stop:      'LifeLogr — Stop', or:  lifelogr --stop"
echo "  - Data:      ~/.local/share/lifelogr/"
echo "  - Logs:      ~/.local/share/lifelogr/server.log"
echo ""
POSTEOF
chmod 755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/prerm" << 'PREEOF'
#!/bin/bash
set -e
# A running per-user instance isn't owned by root; we leave it for the user
# to stop (`lifelogr --stop`). No system service to tear down.
true
PREEOF
chmod 755 "$STAGE/DEBIAN/prerm"

cat > "$STAGE/DEBIAN/postrm" << 'POSTEOF'
#!/bin/bash
set -e
if [ "$1" = "purge" ]; then
    rm -rf /opt/lifelogr /var/cache/lifelogr-uv
    rm -f /usr/share/applications/LifeLogr.desktop /usr/share/applications/LifeLogr-stop.desktop
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
fi
POSTEOF
chmod 755 "$STAGE/DEBIAN/postrm"

# ── 5. Build the .deb ─────────────────────────────────────────────────────
echo "[4/4] Building .deb package..."
dpkg-deb --build "$STAGE" "$ROOT/dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"

DEB_SIZE=$(du -sh "$ROOT/dist/${PKG_NAME}_${VERSION}_${ARCH}.deb" | cut -f1)
echo ""
echo "=== Done: dist/${PKG_NAME}_${VERSION}_${ARCH}.deb ($DEB_SIZE) ==="
echo ""
echo "Install:  sudo dpkg -i dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"
echo "          (builds the venv on first install — needs network)"
echo "Launch:   lifelogr   (or 'LifeLogr' in the app menu)"
echo "Stop:     lifelogr --stop"
echo "Purge:    sudo dpkg --purge ${PKG_NAME}"
