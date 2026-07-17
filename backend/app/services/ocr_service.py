"""Tesseract OCR helper shared by the entry-media and note-media routers.

Centralising the pytesseract/PIL call means both OCR endpoints behave
identically and share the same friendly error story: callers translate a
missing optional dependency into HTTP 501 and a missing ``tesseract`` system
binary into HTTP 500 with an install hint.
"""

from __future__ import annotations

import io


def ocr_image_bytes(file_data: bytes) -> str:
    """Run Tesseract OCR on raw image bytes and return the recognized text.

    Imports are lazy so a missing optional dependency surfaces as
    ``ImportError`` (routers map this to HTTP 501) rather than failing at
    module import time. A missing ``tesseract`` system binary raises
    ``FileNotFoundError`` (an ``OSError``), which routers map to a friendly
    HTTP 500.
    """
    import pytesseract  # type: ignore[import-untyped]
    from PIL import Image

    return str(pytesseract.image_to_string(Image.open(io.BytesIO(file_data))))
