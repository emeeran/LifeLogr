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
