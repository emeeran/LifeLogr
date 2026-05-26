"""Pydantic schemas for OCR endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OCRRequest(BaseModel):
    language: str = Field(
        default="eng", max_length=10, description="Tesseract language code (e.g. eng, fra, deu)"
    )

    model_config = ConfigDict(json_schema_extra={"example": {"language": "eng"}})


class OCRResponse(BaseModel):
    media_id: int
    extracted_text: str
    confidence: float
    language: str
    processed_at: datetime

    model_config = ConfigDict(from_attributes=True)
