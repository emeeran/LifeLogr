# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the LifeLogr FastAPI backend.

Build: cd desktop && make build-backend
Output: dist/lifelogr-backend (single binary)
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, collect_data_files

# Project root (two levels up from this file)
ROOT = Path(SPECPATH).resolve().parent.parent

# Auto-discover all app.* submodules — future-proof against additions
_app_hiddenimports = collect_submodules('app')

# Audio capture/encode — sounddevice + bundled PortAudio (libportaudio) for
# microphone capture, and soundfile + libsndfile for Ogg/Vorbis encoding. Audio
# notes are recorded in the backend (the webview's MediaRecorder is unreliable
# in the packaged WebKit2GTK build). The transcription/STT stack
# (faster-whisper + CTranslate2/onnxruntime/tokenizers + the model bundle) was
# removed when transcription was dropped.
_sounddevice_submodules = collect_submodules('sounddevice')
_sounddevice_binaries = collect_dynamic_libs('sounddevice')
_sounddevice_datas = collect_data_files('sounddevice')
_soundfile_submodules = collect_submodules('soundfile')
_soundfile_binaries = collect_dynamic_libs('soundfile')
_soundfile_datas = collect_data_files('soundfile')

# TTS stack — Edge TTS + aiohttp + certifi (with its cacert.pem data file, so
# HTTPS to the Microsoft TTS service works in the frozen build). Without
# certifi's CA bundle the TLS handshake fails and Read Aloud returns 500.
import os as _os
_edge_tts_hiddenimports = collect_submodules('edge_tts')
_aiohttp_submodules = collect_submodules('aiohttp')
_certifi_submodules = collect_submodules('certifi')
import certifi as _certifi_mod
_certifi_data = [(_os.path.join(_os.path.dirname(_certifi_mod.__file__), 'cacert.pem'), 'certifi')]

# pysqlite3-binary ships its own libsqlite3 and C extension — include both
# so that PyInstaller builds use a known-good sqlite3 instead of the one
# statically compiled into uv's libpython (which breaks qualified col refs).
_site = str(ROOT / 'backend' / '.venv' / 'lib' / 'python3.11' / 'site-packages')
_pysqlite3_binaries = [
    (_site + '/pysqlite3/_sqlite3.cpython-311-x86_64-linux-gnu.so', 'pysqlite3'),
]
# Find the vendored libsqlite3 shared lib (name includes a hash, so glob it)
import glob as _glob
for _so in _glob.glob(_site + '/pysqlite3_binary.libs/libsqlite3*.so*'):
    _pysqlite3_binaries.append((_so, 'pysqlite3_binary.libs'))

a = Analysis(
    [str(ROOT / 'backend' / 'app' / 'main.py')],
    pathex=[str(ROOT / 'backend')],
    binaries=[
        *_pysqlite3_binaries,
        *_sounddevice_binaries,
        *_soundfile_binaries,
    ],
    datas=[
        (str(ROOT / 'backend' / 'app'), 'app'),
        # certifi CA bundle — required for Edge TTS HTTPS in the frozen build.
        *_certifi_data,
        # sounddevice's bundled PortAudio + soundfile's libsndfile libraries.
        *_sounddevice_datas,
        *_soundfile_datas,
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
        # pysqlite3 — bundles a reliable sqlite3 with FTS5
        'pysqlite3',
        # TTS — Edge TTS for Read Aloud
        *_edge_tts_hiddenimports,
        *_aiohttp_submodules,
        'certifi',
        *_certifi_submodules,
        'aiohttp',
        'numpy',
        'numpy.core',
        'yaml',
        # Audio capture/encode — sounddevice (mic capture) + soundfile/_soundfile
        # (Ogg/Vorbis encode via libsndfile) + cffi (their C bindings)
        'sounddevice',
        *_sounddevice_submodules,
        'soundfile',
        *_soundfile_submodules,
        '_soundfile',
        'cffi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy optional deps NOT needed by the STT stack — excluded for size.
        # (faster-whisper uses CTranslate2, not torch.)
        'weasyprint',
        'mega',
        'PIL',
        'PIL.Image',
        'pytesseract',
        'torch',
        'scipy',
        'matplotlib',
        # Unused Python stdlib — strip for size
        'tkinter',
        # 'unittest' kept — required by fpdf (unittest.mock)
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
    name='lifelogr-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    console=sys.platform != 'win32',  # Hide cmd window on Windows
    argv_emulation=False,
)
