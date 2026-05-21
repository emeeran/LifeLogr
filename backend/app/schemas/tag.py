"""Pydantic schemas for tags."""
from pydantic import BaseModel, ConfigDict, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="Tag name; case-insensitive unique")
    parent_id: int | None = Field(default=None, description="Parent tag ID for hierarchy")

    model_config = ConfigDict(json_schema_extra={"example": {"name": "europe", "parent_id": 5}})


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="New tag name")

    model_config = ConfigDict(json_schema_extra={"example": {"name": "asia"}})


class TagBrief(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class TagResponse(BaseModel):
    id: int
    name: str
    parent_id: int | None
    children: list[TagBrief]
    entry_count: int

    model_config = ConfigDict(from_attributes=True)
