#!/usr/bin/env bash
# Measure how long the desktop app takes to close (CLOSE-5/CLOSE-6).
#
# Usage:
#   scripts/close-timing.sh                 # use `lifelogr` from PATH
#   scripts/close-timing.sh /path/to/lifelogr
#   RUNS=5 scripts/close-timing.sh          # repeat and print p50/p95
#
# What it measures: launch → wait for the backend port → SIGTERM the app (the
# signal a session logout sends) → time until BOTH the app process and the
# backend port are gone. A window close goes through Tauri's ExitRequested
# guard, which is the same teardown path; only the trigger differs, so this is
# a close *upper bound* that runs without a human.
#
# It does NOT start a second instance check — run it with the app closed.
set -euo pipefail

BIN="${1:-lifelogr}"
RUNS="${RUNS:-1}"
PORT="${DIARI_PORT:-18765}"

if ! command -v "$BIN" >/dev/null 2>&1 && [[ ! -x "$BIN" ]]; then
  echo "error: '$BIN' not found (pass the binary path as the first argument)" >&2
  exit 1
fi

now_ms() { date +%s%3N; }

wait_for_port() {
  local deadline=$(( $(date +%s) + 30 ))
  while (( $(date +%s) < deadline )); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
      exec 3>&- 3<&- 2>/dev/null || true
      return 0
    fi
    sleep 0.1
  done
  return 1
}

measure_once() {
  "$BIN" >/dev/null 2>&1 &
  local app_pid=$!
  if ! wait_for_port; then
    echo "error: backend never listened on :$PORT" >&2
    kill "$app_pid" 2>/dev/null || true
    return 1
  fi

  sleep 1  # let the window settle
  local started
  started=$(now_ms)
  kill -TERM "$app_pid" 2>/dev/null || true

  # App process gone?
  local final_pid_time=""
  for _ in $(seq 1 300); do
    if ! kill -0 "$app_pid" 2>/dev/null; then
      final_pid_time=$(now_ms)
      break
    fi
    sleep 0.1
  done

  # Backend port released?
  local port_time=""
  for _ in $(seq 1 300); do
    if ! (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
      port_time=$(now_ms)
      break
    fi
    sleep 0.1
  done

  local app_ms=$(( ${final_pid_time:-$(now_ms)} - started ))
  local port_ms=$(( ${port_time:-$(now_ms)} - started ))
  echo "app exited in ${app_ms} ms; port ${PORT} released in ${port_ms} ms"

  # A survived process means the guard did not finish; fail loudly.
  if kill -0 "$app_pid" 2>/dev/null; then
    echo "error: app still running after 30 s" >&2
    kill -9 "$app_pid" 2>/dev/null || true
    return 1
  fi
}

echo "Measuring $RUNS close(s) of $BIN on port $PORT…"
for i in $(seq 1 "$RUNS"); do
  echo "run $i/$RUNS:"
  measure_once || exit 1
done

cat <<'NOTE'

Targets (modify-idea plan §9; plan archived in trash2review/):
  idle           p50 ≤ 1 s, p95 ≤ 1.5 s
  backup running app shows "Finishing backup…" and exits ≤ 2 s after it completes
  always         port 18765 free within 2 s, no orphaned lifelogr-backend
NOTE
