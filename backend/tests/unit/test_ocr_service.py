"""Unit tests for the shared OCR helper (real tesseract, when available)."""

import shutil

import pytest


def _has_tesseract() -> bool:
    return shutil.which("tesseract") is not None


@pytest.mark.skipif(not _has_tesseract(), reason="tesseract binary not installed")
def test_ocr_image_bytes_reads_rendered_text():
    import io

    from PIL import Image, ImageDraw, ImageFont

    from app.services.ocr_service import ocr_image_bytes

    font = ImageFont.load_default(size=48)
    img = Image.new("RGB", (300, 80), "white")
    ImageDraw.Draw(img).text((12, 14), "CLIP42", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    text = ocr_image_bytes(buf.getvalue())
    assert "CLIP42" in text.upper()


def test_ocr_image_bytes_rejects_unsupported_language():
    """The whitelist check runs before any tesseract call, so it needs no binary."""
    from app.services.ocr_service import ocr_image_bytes

    with pytest.raises(ValueError):
        ocr_image_bytes(b"\x00", lang="not-a-real-language")


def test_supported_ocr_langs_match_ui_picker():
    """The whitelist must stay in sync with the Settings → Appearance picker's
    language codes; drift here means a UI-selectable language silently 400s."""
    from app.services.ocr_service import SUPPORTED_OCR_LANGS

    assert SUPPORTED_OCR_LANGS == frozenset({"eng", "tam"})


def test_bundled_tesseract_used_when_frozen(monkeypatch, tmp_path):
    """Windows sidecar: pytesseract must point at the bundled binary + tessdata
    (pyinstaller.spec collects desktop/vendor/tesseract next to _MEIPASS)."""
    import os
    import sys

    import pytesseract

    from app.services import ocr_service

    bundle = tmp_path / "tesseract"
    bundle.mkdir()
    (bundle / "tesseract.exe").write_bytes(b"")
    (bundle / "tessdata").mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    # setenv registers the original for restore — _configure_bundled_tesseract
    # overwrites it via os.environ, which monkeypatch wouldn't otherwise undo.
    monkeypatch.setenv("TESSDATA_PREFIX", "stale")
    monkeypatch.delenv("LIFELOGR_TESSERACT_CMD", raising=False)

    ocr_service._configure_bundled_tesseract(pytesseract)

    assert pytesseract.pytesseract.tesseract_cmd == str(bundle / "tesseract.exe")
    assert os.environ["TESSDATA_PREFIX"] == str(bundle / "tessdata")


def test_unfrozen_run_keeps_path_tesseract(monkeypatch):
    """Dev/Linux runs: nothing frozen, nothing bundled — apt tesseract stays."""
    import sys

    import pytesseract

    from app.services import ocr_service

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    monkeypatch.delenv("LIFELOGR_TESSERACT_CMD", raising=False)

    ocr_service._configure_bundled_tesseract(pytesseract)

    assert pytesseract.pytesseract.tesseract_cmd == "tesseract"
