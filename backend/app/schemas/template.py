"""Pydantic schemas for template CRUD."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Daily Reflection",
                "body": "## How I'm feeling\n\n\n## What I did today\n\n",
            }
        }
    )


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    body: str | None = Field(default=None, min_length=1)


class TemplateResponse(BaseModel):
    id: int
    name: str
    body: str
    is_builtin: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
