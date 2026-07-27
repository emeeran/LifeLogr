#!/usr/bin/env python3
"""Assert the app version is consistent across all four source-of-truth files.

LifeLogr's version is duplicated in four places (see ``make bump``); a manual
edit to any one drifts silently and ships a mismatched bundle. This script
extracts each and exits non-zero if they disagree, so CI catches the drift
before release. Run locally with ``make check-version``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (ROOT / "backend" / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise RuntimeError("Could not find version in backend/pyproject.toml")
    return m.group(1)


def _config_version() -> str:
    text = (ROOT / "backend" / "app" / "core" / "config.py").read_text()
    m = re.search(r'APP_VERSION:\s*str\s*=\s*"([^"]+)"', text)
    if not m:
        raise RuntimeError("Could not find APP_VERSION in backend/app/core/config.py")
    return m.group(1)


def _cargo_version() -> str:
    text = (ROOT / "desktop" / "src-tauri" / "Cargo.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise RuntimeError("Could not find version in desktop/src-tauri/Cargo.toml")
    return m.group(1)


def _tauri_conf_version() -> str:
    data = json.loads((ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text())
    if "version" not in data:
        raise RuntimeError("Could not find version in desktop/src-tauri/tauri.conf.json")
    return str(data["version"])


def main() -> int:
    sources = {
        "backend/pyproject.toml": _pyproject_version(),
        "backend/app/core/config.py": _config_version(),
        "desktop/src-tauri/Cargo.toml": _cargo_version(),
        "desktop/src-tauri/tauri.conf.json": _tauri_conf_version(),
    }
    print("Version sources:")
    for name, value in sources.items():
        print(f"  {name}: {value}")
    versions = set(sources.values())
    if len(versions) != 1:
        print(
            "\n✘ Version drift detected — run `make bump V=<version>` to sync "
            "all four sources.",
            file=sys.stderr,
        )
        return 1
    print(f"\n✔ All four sources agree: {next(iter(versions))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
