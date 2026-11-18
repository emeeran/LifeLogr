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

# Image handling + OCR — Pillow (webp compression/thumbnails + OCR image input)
# and pytesseract. collect_submodules pulls the whole PIL package (plugins
# register themselves in PIL/__init__._plugins); the *diet* is done via the
# excludes block below, which prunes every format plugin the backend cannot
# receive. Pillow's init() swallows the per-plugin ImportError, so excluded
# plugins just never register and those formats report UnidentifiedImageError.
_pil_submodules = collect_submodules('PIL')
_pil_binaries = collect_dynamic_libs('PIL')

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
# so frozen Linux builds use a known-good sqlite3 (the qualified-column fix).
# It's Linux-only (no Windows/macOS wheels), so collection is guarded by
# import: where pysqlite3 is absent, app/main.py falls back to stdlib sqlite3
# and we bundle nothing here. Paths are resolved from the installed package
# (not a hardcoded Linux venv path) so this works on any platform.
import glob as _glob
_pysqlite3_binaries = []
_pysqlite3_hiddenimports = []
try:
    import pysqlite3 as _pysqlite3_mod
    _pkg = _os.path.dirname(_pysqlite3_mod.__file__)
    # Compiled extension: _sqlite3.<ext> (.so on Linux, .pyd on Windows).
    for _ext in _glob.glob(_os.path.join(_pkg, '_sqlite3.*')):
        _pysqlite3_binaries.append((_ext, 'pysqlite3'))
    # Vendored libsqlite3 lives in a sibling .libs dir (hash in the name).
    for _lib in _glob.glob(_os.path.join(_pkg, '..', 'pysqlite3_binary.libs', 'libsqlite3*')):
        _pysqlite3_binaries.append((_lib, 'pysqlite3_binary.libs'))
    _pysqlite3_hiddenimports.append('pysqlite3')
except ImportError:
    pass  # pysqlite3 not installed (Windows/macOS) — stdlib sqlite3 fallback

a = Analysis(
    [str(ROOT / 'backend' / 'app' / 'main.py')],
    pathex=[str(ROOT / 'backend')],
    binaries=[
        *_pysqlite3_binaries,
        *_sounddevice_binaries,
        *_soundfile_binaries,
        *_pil_binaries,
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
        # pysqlite3 — bundles a reliable sqlite3 with FTS5 (Linux only)
        *_pysqlite3_hiddenimports,
        # TTS — Edge TTS for Read Aloud
        *_edge_tts_hiddenimports,
        *_aiohttp_submodules,
        'certifi',
        *_certifi_submodules,
        'aiohttp',
        'yaml',
        # Audio capture/encode — sounddevice (mic capture) + soundfile/_soundfile
        # (Ogg/Vorbis encode via libsndfile) + cffi (their C bindings)
        'sounddevice',
        *_sounddevice_submodules,
        'soundfile',
        *_soundfile_submodules,
        '_soundfile',
        'cffi',
        # Image + OCR — Pillow (webp compression + OCR image input) + pytesseract
        'PIL',
        *_pil_submodules,
        'pytesseract',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy optional deps NOT needed — excluded for size.
        'weasyprint',
        'mega',
        'torch',
        'scipy',
        'matplotlib',
        # numpy STAYS (LW-2.1 outcome): semantic_cache.py no longer uses it,
        # but services/recording_service.py requires it (FFT high-pass, spectral
        # gate, frames→Ogg encode) — excluding it would break voice recording
        # in frozen builds. Revisit only with a `voice` optional-extra +
        # feature-detect design decision.
        # PIL plugin diet (LW-1.2) — keep ONLY the formats the backend can
        # actually receive: media_service._CONVERTIBLE_IMAGE_TYPES accepts
        # PNG/JPEG/WebP/BMP/TIFF (all converted to WebP on import), plus GIF
        # (a common image/* upload that only needs a thumbnail) and MPO
        # (JPEG's multi-picture sibling, handled by the same codec). WebP
        # save and JPEG/PNG/WebP/BMP/TIFF/GIF decode cover media_service
        # thumbs, the WebP convert path, and ocr_service's image input.
        # Everything else in PIL/__init__._plugins is excluded; PIL.Image.init()
        # swallows the per-plugin ImportError, so this degrades to
        # UnidentifiedImageError for the dropped formats. Also drop the
        # font/colour-management stacks — nothing draws text or converts ICC —
        # which keeps the bundled freetype/littlecms native libs out of the
        # exe. (PyInstaller's own hook-PIL.Image force-collects all
        # *ImagePlugin modules, but Analysis excludes win over hook
        # hiddenimports, so these are the single source of truth.)
        'PIL.AvifImagePlugin',
        'PIL.BlpImagePlugin',
        'PIL.BufrStubImagePlugin',
        'PIL.CurImagePlugin',
        'PIL.DcxImagePlugin',
        'PIL.DdsImagePlugin',
        'PIL.EpsImagePlugin',
        'PIL.FitsImagePlugin',
        'PIL.FliImagePlugin',
        'PIL.FpxImagePlugin',
        'PIL.FtexImagePlugin',
        'PIL.GbrImagePlugin',
        'PIL.GribStubImagePlugin',
        'PIL.Hdf5StubImagePlugin',
        'PIL.IcnsImagePlugin',
        'PIL.IcoImagePlugin',
        'PIL.ImImagePlugin',
        'PIL.ImtImagePlugin',
        'PIL.IptcImagePlugin',
        'PIL.Jpeg2KImagePlugin',
        'PIL.McIdasImagePlugin',
        'PIL.MicImagePlugin',
        'PIL.MpegImagePlugin',
        'PIL.MspImagePlugin',
        'PIL.PalmImagePlugin',
        'PIL.PcdImagePlugin',
        'PIL.PcxImagePlugin',
        'PIL.PdfImagePlugin',
        'PIL.PixarImagePlugin',
        'PIL.PpmImagePlugin',
        'PIL.PsdImagePlugin',
        'PIL.QoiImagePlugin',
        'PIL.SgiImagePlugin',
        'PIL.SpiderImagePlugin',
        'PIL.SunImagePlugin',
        'PIL.TgaImagePlugin',
        'PIL.WmfImagePlugin',
        'PIL.XbmImagePlugin',
        'PIL.XpmImagePlugin',
        'PIL.XVThumbImagePlugin',
        'PIL.ImageCms',
        'PIL.ImageFont',
        'PIL.ImageShow',
        'PIL.ImageGrab',
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
        # NOTE: imaplib & smtplib are intentionally NOT excluded — the email
        # stack needs them (email_protocol uses imaplib; aiosmtplib wraps
        # smtplib). Excluding either breaks the frozen binary at import time.
        'nntplib',
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
