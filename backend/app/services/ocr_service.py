"""Tesseract OCR helper shared by the entry-media and note-media routers.

Centralising the pytesseract/PIL call means both OCR endpoints behave
identically and share the same friendly error story: callers translate a
missing optional dependency into HTTP 501 and a missing ``tesseract`` system
binary into HTTP 500 with an install hint.
"""

from __future__ import annotations

import io

# Language codes offered in the frontend Settings → Appearance → "OCR language"
# picker. Only English and Tamil are shipped — both have Tesseract data packs
# installed on the target device. The value arrives over the wire and is passed
# to the tesseract CLI, so we whitelist it: an unknown/garbage code is rejected
# with ValueError rather than handed to the binary.
SUPPORTED_OCR_LANGS: frozenset[str] = frozenset(
    {
        "eng",
        "tam",
    }
)


class OcrLanguageUnavailable(RuntimeError):
    """The requested OCR language's trained data isn't installed for tesseract.

    Distinct from a missing ``tesseract`` binary (``FileNotFoundError``): here
    tesseract runs but can't load the language. Routers map this to HTTP 500
    with a message naming the language and an install hint.
    """


def ocr_image_bytes(file_data: bytes, lang: str = "eng") -> str:
    """Run Tesseract OCR on raw image bytes and return the recognized text.

    ``lang`` is a tesseract language code (e.g. ``"eng"``, ``"jpn"``); it must
    appear in :data:`SUPPORTED_OCR_LANGS` or a ``ValueError`` is raised.

    Imports are lazy so a missing optional dependency surfaces as
    ``ImportError`` (routers map this to HTTP 501) rather than failing at
    module import time. A missing ``tesseract`` system binary raises
    ``FileNotFoundError`` (an ``OSError``), which routers map to a friendly
    HTTP 500. A present binary but missing language data raises
    :class:`OcrLanguageUnavailable` (also HTTP 500, with a language-specific
    hint).
    """
    if lang not in SUPPORTED_OCR_LANGS:
        raise ValueError(f"Unsupported OCR language: {lang!r}")

    import pytesseract  # type: ignore[import-untyped]
    from PIL import Image

    try:
        return str(pytesseract.image_to_string(Image.open(io.BytesIO(file_data)), lang=lang))
    except pytesseract.TesseractError as exc:
        # Most common cause: the language's traineddata file isn't installed.
        raise OcrLanguageUnavailable(
            f"OCR language {lang!r} isn't available. Install its Tesseract "
            f"language data (e.g. tesseract-ocr-{lang.replace('_', '-')}) "
            "and retry."
        ) from exc
