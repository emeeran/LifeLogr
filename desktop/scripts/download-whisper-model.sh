#!/usr/bin/env bash
# Pre-download the faster-whisper model so the packaged app can transcribe
# offline, with no network access and no first-run delay.
#
# Outputs: backend/app/models/faster-whisper-<MODEL>/  (bundled by PyInstaller)
#
# Usage:   ./desktop/scripts/download-whisper-model.sh [model_size]
# Default model is "base" (~148 MB). Override via $1 or WHISPER_MODEL env.
#
# The bundled path is resolved at runtime by VoiceRecordingService via
# settings.WHISPER_MODEL, so the model name here MUST match config.py.

set -euo pipefail

MODEL="${1:-${WHISPER_MODEL:-base}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT="$ROOT/backend/models/faster-whisper-$MODEL"

echo "→ Downloading faster-whisper model '$MODEL' into $OUT"

cd "$ROOT/backend"
uv run python - "$MODEL" "$OUT" <<'PYEOF'
import os, shutil, sys
from huggingface_hub import snapshot_download
model, out = sys.argv[1], sys.argv[2]
# Wipe a previous download so a model-name change doesn't leave stale files.
if os.path.isdir(out):
    shutil.rmtree(out)
os.makedirs(out, exist_ok=True)
path = snapshot_download(repo_id=f"Systran/faster-whisper-{model}", local_dir=out)
# Drop HF metadata cache (not needed at runtime; saves space in the bundle).
cache = os.path.join(out, ".cache")
if os.path.isdir(cache):
    shutil.rmtree(cache)
# Report size.
total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs)
print(f"✓ {model} model ready at {out} ({total / 1e6:.1f} MB)")
PYEOF

echo "→ Model staged at: $OUT"
