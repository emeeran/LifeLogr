# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Diarilinux FastAPI backend.

Build: cd desktop && make build-backend
Output: dist/diarilinux-backend (single binary)
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# Project root (two levels up from this file)
ROOT = Path(SPECPATH).resolve().parent.parent

# Auto-discover all app.* submodules — future-proof against additions
_app_hiddenimports = collect_submodules('app')

a = Analysis(
    [str(ROOT / 'backend' / 'app' / 'main.py')],
    pathex=[str(ROOT / 'backend')],
    binaries=[],
    datas=[
        (str(ROOT / 'backend' / 'app'), 'app'),
    ],
    hiddenimports=[
        # Auto-discovered app modules
        *_app_hiddenimports,
        # Uvicorn (ASGI server)
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # Third-party
        'aiosqlite',
        'httpx',
        'apscheduler',
        'apscheduler.schedulers',
        'apscheduler.schedulers.asyncio',
        'apscheduler.triggers',
        'apscheduler.triggers.cron',
        'sqlalchemy.ext.asyncio',
        'sqlalchemy.orm',
        'fpdf',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy optional deps — excluded for size; install via [group] extras
        'faster_whisper',
        'weasyprint',
        'edge_tts',
        'mega',
        'PIL',
        'PIL.Image',
        'pytesseract',
        'torch',
        'numpy',
        'scipy',
        'matplotlib',
        # Unused Python stdlib — strip for size
        'tkinter',
        'unittest',
        'test',
        'tests',
        'xmlrpc',
        'pydoc',
        'doctest',
        'distutils',
        'lib2to3',
        'curses',
        'tty',
        'webbrowser',
        'antigravity',
        'this',
        'imaplib',
        'nntplib',
        'smtplib',
        'poplib',
        'telnetlib',
        'ftplib',
        'winsound',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='diarilinux-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=sys.platform != 'win32',  # Hide cmd window on Windows
    argv_emulation=False,
)
