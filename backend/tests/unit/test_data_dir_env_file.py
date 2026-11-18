"""DATA_DIR/.env supplements the packaged backend's settings.

The desktop sidecar's PyInstaller backend has no project checkout beside it,
so without this file OAuth credentials were unreachable in the installed app
(dev reads ``backend/.env`` from the cwd; the packaged app reads nothing).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_PROBE = (
    "from app.core.config import Settings; "
    "import json; print(json.dumps({'id': Settings().GOOGLE_CLIENT_ID}))"
)


def _probe_with(data_dir: Path) -> str:
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "DATA_DIR": str(data_dir)},
        cwd=Path(__file__).resolve().parents[2],
    ).stdout.strip()


def test_data_dir_env_file_supplies_oauth_credentials(tmp_path: Path) -> None:
    """A managed run reads GOOGLE_CLIENT_ID from its data dir's .env."""
    (tmp_path / ".env").write_text("GOOGLE_CLIENT_ID=desktop-client-id\n")
    assert json.loads(_probe_with(tmp_path))["id"] == "desktop-client-id"


def test_env_var_beats_data_dir_env_file(tmp_path: Path) -> None:
    """A real environment variable wins over the data-dir file, as with .env."""
    (tmp_path / ".env").write_text("GOOGLE_CLIENT_ID=from-file\n")
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "DATA_DIR": str(tmp_path),
            "GOOGLE_CLIENT_ID": "from-env",
        },
        cwd=Path(__file__).resolve().parents[2],
    ).stdout.strip()
    assert json.loads(out)["id"] == "from-env"
