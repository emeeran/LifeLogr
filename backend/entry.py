"""PyInstaller entry point for the Windows sidecar.

With console=False, an unhandled startup exception surfaces as an invisible
"Failed to execute script" dialog and the process hangs - useless on an
unattended runner and inscrutable for a user. This wrapper appends its
progress and any fatal traceback to %TEMP%\\lifelogr-backend-crash.log and
exits non-zero, so a failed or stuck start is diagnosable from the file
alone: "invoked" without a traceback means the hang is inside app startup;
no line at all means the PyInstaller bootloader never ran Python.
Stdlib-only imports up top: even a failure importing app.* gets logged.
"""

import sys
import tempfile
import traceback
from pathlib import Path

CRASH_LOG = Path(tempfile.gettempdir()) / "lifelogr-backend-crash.log"


def _mark(message: str) -> None:
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except OSError:
        pass


def run() -> None:
    from app.main import main

    main()


if __name__ == "__main__":
    _mark(f"entry.py invoked (python {sys.version.split()[0]}, frozen={getattr(sys, 'frozen', False)})")
    try:
        run()
        _mark("run() returned normally")
    except BaseException:
        _mark(traceback.format_exc())
        sys.exit(1)
