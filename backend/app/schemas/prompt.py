"""Pydantic schemas for daily prompts."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class PromptResponse(BaseModel):
    id: int
    prompt_text: str
    active_date: date

    model_config = ConfigDict(from_attributes=True)
