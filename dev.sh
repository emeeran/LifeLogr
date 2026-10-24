#!/usr/bin/env bash
# dev.sh — Launch both frontend and backend on available ports.
# Usage: ./dev.sh
# Stops both servers cleanly on Ctrl+C.

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────────────────

find_free_port() {
    python3 -c "
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(('', 0))
    print(s.getsockname()[1])
"
}

cleanup() {
    echo ""
    echo "Stopping servers..."
    [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    wait 2>/dev/null
    echo "Done."
    exit 0
}

trap cleanup INT TERM

# ── Resolve paths ────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# ── Find available ports ────────────────────────────────────────────────────

BACKEND_PORT=$(find_free_port)
FRONTEND_PORT=$(find_free_port)

# ── Launch backend ───────────────────────────────────────────────────────────

echo "Starting backend on port $BACKEND_PORT"
(
    cd "$BACKEND_DIR"
    VITE_BACKEND_PORT="$BACKEND_PORT" uv run uvicorn app.main:app --reload --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

# ── Launch frontend ──────────────────────────────────────────────────────────

echo "Starting frontend on port $FRONTEND_PORT"
(
    cd "$FRONTEND_DIR"
    VITE_BACKEND_PORT="$BACKEND_PORT" npx vite --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

# ── Wait ─────────────────────────────────────────────────────────────────────

echo ""
echo "Backend  → http://localhost:$BACKEND_PORT"
echo "Frontend → http://localhost:$FRONTEND_PORT"
echo "Press Ctrl+C to stop both servers."
echo ""

wait
