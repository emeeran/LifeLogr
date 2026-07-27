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

# ── 1. System packages (gstreamer, OCR, audio) ──
install_system_deps() {
    echo ">>> Installing system packages..."

    case "$DISTRO" in
        ubuntu|debian|linuxmint|pop)
            apt-get update -qq
            apt-get install -y --no-install-recommends \
                libffi-dev shared-mime-info \
                gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav \
                gstreamer1.0-plugins-bad \
                libportaudio2 \
                tesseract-ocr tesseract-ocr-eng
            ;;
        fedora|rhel|centos)
            dnf install -y libffi shared-mime-info
            ;;
        arch|manjaro|endeavouros)
            pacman -S --needed --noconfirm libffi shared-mime-info
            ;;
        opensuse*|sles)
            zypper install -y libffi shared-mime-info
            ;;
        *)
            warn "Unsupported distro: $DISTRO"
            warn "Install manually: libffi, shared-mime-info"
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

# ── 3. Verify installation ──
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
verify_install
