#!/usr/bin/env bash
set -euo pipefail

# Build orchestrator for LifeLogr
# Usage: ./scripts/build.sh [target]
# Targets: linux, windows, mac, android, ios, all-desktop, all

TARGET="${1:-linux}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== LifeLogr Build: $TARGET ==="

# ── Prerequisite checks ────────────────────────────────────────────────
need_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo "ERROR: '$1' is required but not installed. $2"
    exit 1
  fi
}

build_frontend() {
  echo "[1/3] Building frontend..."
  need_cmd npm "Install Node.js: https://nodejs.org"
  cd "$ROOT/frontend"
  npm ci
  npm run build
  echo "Frontend built: frontend/dist/"
}

build_backend_binary() {
  echo "[2/3] Building backend binary (PyInstaller)..."
  need_cmd uv "Install uv: https://docs.astral.sh/uv/"
  cd "$ROOT/backend"
  uv sync --extra tts
  # Install pyinstaller into the backend venv (idempotent)
  uv pip install pyinstaller
  cd "$ROOT/desktop"
  "$ROOT/backend/.venv/bin/pyinstaller" scripts/pyinstaller.spec \
    --noconfirm \
    --distpath dist/backend \
    --workpath build/backend
  echo "Backend binary: dist/backend/lifelogr-backend/"
}

build_tauri() {
  echo "[3/3] Building Tauri app..."
  need_cmd rustc "Install Rust: https://rustup.rs"
  need_cmd cargo "Install Rust: https://rustup.rs"

  # Ensure tauri-cli is installed
  if ! cargo tauri --version &>/dev/null; then
    echo "Installing tauri-cli..."
    cargo install tauri-cli
  fi

  cd "$ROOT/desktop"

  # PyInstaller onefile outputs: dist/backend/lifelogr-backend (single binary)
  # Tauri sidecar expects the binary next to tauri.conf.json with target-triple suffix
  local target_triple
  target_triple="$(rustc -vV | grep host | cut -d' ' -f2)"
  cp "dist/backend/lifelogr-backend" "src-tauri/lifelogr-backend-${target_triple}"
  chmod +x "src-tauri/lifelogr-backend-${target_triple}"

  echo "Sidecar ready: src-tauri/lifelogr-backend-${target_triple}"
  cd src-tauri && cargo tauri build
  echo "Packages: src-tauri/target/release/bundle/"
}

build_mobile() {
  local platform="$1"
  echo "[Mobile] Building for $platform..."
  need_cmd npm "Install Node.js: https://nodejs.org"
  cd "$ROOT/frontend"
  npm ci
  VITE_PLATFORM=capacitor npm run build
  cd "$ROOT/mobile"

  if [ ! -f package.json ]; then
    npm init -y
  fi
  npm install @capacitor/core @capacitor/cli @capacitor-community/sqlite "@capacitor/$platform"

  # Add platform if not already added
  if [ ! -d "$platform" ]; then
    npx cap add "$platform"
  fi
  npx cap sync

  if [ "$platform" = "android" ]; then
    cd android && ./gradlew assembleRelease
    echo "APK: android/app/build/outputs/apk/release/"
  else
    echo "Open Xcode: mobile/ios/App/App.xcworkspace"
  fi
}

case "$TARGET" in
  linux|windows|mac)
    build_frontend
    build_backend_binary
    build_tauri
    ;;
  android|ios)
    build_mobile "$TARGET"
    ;;
  all-desktop)
    build_frontend
    build_backend_binary
    build_tauri
    ;;
  all)
    build_frontend
    build_backend_binary
    build_tauri
    build_mobile android
    build_mobile ios
    ;;
  *)
    echo "Unknown target: $TARGET"
    echo "Usage: $0 [linux|windows|mac|android|ios|all-desktop|all]"
    exit 1
    ;;
esac

echo "=== Build complete ==="
