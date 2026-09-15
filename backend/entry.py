"""PyInstaller entry point for the Windows sidecar.

With console=False, an unhandled startup exception surfaces as an invisible
"Failed to execute script" dialog and the process hangs - useless on an
unattended runner and inscrutable for a user. This wrapper writes any fatal
traceback to %TEMP%\\lifelogr-backend-crash.log before exiting non-zero, so a
failed start is diagnosable from the file alone. Stdlib-only imports up top:
even a failure importing app.* (config paths, DB init, routers) gets logged.
"""

import sys
import tempfile
import traceback
from pathlib import Path

CRASH_LOG = Path(tempfile.gettempdir()) / "lifelogr-backend-crash.log"


def run() -> None:
    from app.main import main

    main()


if __name__ == "__main__":
    try:
        run()
    except BaseException:
        try:
            CRASH_LOG.write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        sys.exit(1)
