#!/usr/bin/env bash
# LifeLogr — First-run system dependency installer
# Installs all system-level deps needed for full app functionality.
# Run: sudo ./setup-linux.sh  (or via the app's Setup dialog)
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ── Root check ──
if [ "$(id -u)" -ne 0 ]; then
    fail "This script must be run as root (use sudo or pkexec)"
fi

# ── Detect distro ──
if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    DISTRO="$ID"
else
    fail "Cannot detect Linux distribution"
fi

echo "LifeLogr System Dependency Setup"
echo "==================================="
echo "Detected distro: $DISTRO"
echo ""

# ── 1. System packages (weasyprint deps, gstreamer) ──
install_system_deps() {
    echo ">>> Installing system packages..."

    case "$DISTRO" in
        ubuntu|debian|linuxmint|pop)
            apt-get update -qq
            apt-get install -y --no-install-recommends \
                libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
                libgdk-pixbuf2.0-0 libffi-dev shared-mime-info \
                gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav \
                gstreamer1.0-plugins-bad \
                libportaudio2
            ;;
        fedora|rhel|centos)
            dnf install -y pango cairo gdk-pixbuf2 libffi shared-mime-info
            ;;
        arch|manjaro|endeavouros)
            pacman -S --needed --noconfirm pango cairo gdk-pixbuf2 libffi shared-mime-info
            ;;
        opensuse*|sles)
            zypper install -y pango cairo gdk-pixbuf libffi shared-mime-info
            ;;
        *)
            warn "Unsupported distro: $DISTRO"
            warn "Install manually: pango, cairo, gdk-pixbuf, libffi"
            return
            ;;
    esac
    log "System packages installed"
}

# ── 2. Ollama (AI grammar check, spell check, rewrite) ──
install_ollama() {
    echo ">>> Setting up Ollama for AI features..."

    if command -v ollama &>/dev/null; then
        log "Ollama already installed — skipping"
    else
        echo "    Downloading Ollama installer..."
        curl -fsSL https://ollama.com/install.sh | sh
        log "Ollama installed"
    fi

    # Start Ollama service if not running
    if ! pgrep -x ollama &>/dev/null; then
        echo "    Starting Ollama service..."
        # Try systemd first, fall back to background process
        if command -v systemctl &>/dev/null; then
            systemctl start ollama 2>/dev/null || ollama serve &>/dev/null &
        else
            ollama serve &>/dev/null &
        fi
        sleep 3
    fi

    # Pull default model (llama3.2:3b — matches config.py OLLAMA_MODEL)
    if ollama list 2>/dev/null | grep -q "llama3.2"; then
        log "AI model (llama3.2) already available"
    else
        echo "    Pulling AI model (llama3.2:3b, ~2GB download)..."
        ollama pull llama3.2:3b
        log "AI model pulled"
    fi
}

# ── 3. Optional: Python deps for voice transcription & PDF export ──
install_python_optional() {
    echo ">>> Installing optional Python packages..."

    # Detect the owner of the home directory when run via sudo
    REAL_HOME="${SUDO_HOME:-${HOME}}"
    if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
        REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    fi

    local VENV="$REAL_HOME/.local/share/lifelogr/python-deps"

    if [ ! -d "$VENV" ]; then
        python3 -m venv "$VENV"
        # Fix ownership when run via sudo
        if [ -n "${SUDO_USER:-}" ]; then
            chown -R "$SUDO_USER:$SUDO_USER" "$VENV"
        fi
    fi

    "$VENV/bin/pip" install --upgrade pip -q 2>/dev/null
    "$VENV/bin/pip" install -q faster-whisper weasyprint 2>/dev/null || \
        warn "Some optional Python deps failed to install (non-critical)"

    # Fix ownership of installed packages
    if [ -n "${SUDO_USER:-}" ]; then
        chown -R "$SUDO_USER:$SUDO_USER" "$VENV"
    fi

    log "Optional Python deps installed to $VENV"
    warn "Note: faster-whisper and weasyprint are optional — not required for core features"
}

# ── 4. Verify installation ──
verify_install() {
    echo ""
    echo "=== Verification ==="
    echo ""

    local all_ok=true

    if command -v ollama &>/dev/null; then
        log "Ollama: installed"
        if ollama list 2>/dev/null | grep -q "llama3.2"; then
            log "AI Model: llama3.2 available"
        else
            warn "AI Model: not pulled (run: ollama pull llama3.2:3b)"
            all_ok=false
        fi
    else
        warn "Ollama: NOT FOUND"
        all_ok=false
    fi

    echo ""
    if $all_ok; then
        log "All dependencies installed! Restart LifeLogr to use all features."
    else
        warn "Some deps are missing — AI features may be limited."
        echo "    Re-run this script or install manually."
    fi
}

# ── Run ──
install_system_deps
install_ollama
install_python_optional
verify_install
