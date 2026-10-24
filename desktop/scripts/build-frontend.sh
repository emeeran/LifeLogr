#!/usr/bin/env bash
# Frontend build used as Tauri's beforeBuildCommand.
#
# Tauri runs hook commands with a CWD that depends on how the CLI was
# invoked, so this script locates itself and never trusts the inherited
# CWD. It mirrors desktop/Makefile's build-frontend target, including the
# VITE_APP_VERSION stamp the plain `npm run build` would omit.
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER="$(grep '^version' "$DESKTOP_DIR/src-tauri/Cargo.toml" | head -1 | sed 's/.*"\(.*\)".*/\1/')"

echo "Building frontend with VITE_APP_VERSION=$VER"
cd "$DESKTOP_DIR/../frontend"
VITE_APP_VERSION="$VER" npm run build
