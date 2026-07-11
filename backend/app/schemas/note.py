"""Pydantic schemas for notes."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tag import TagBrief


class NoteFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="Folder name")
    parent_id: int | None = Field(
        default=None, description="Parent folder ID (nesting reserved for future)"
    )
    color: str | None = Field(default=None, max_length=20, description="Optional color label")
    sort_order: int = Field(default=0, ge=0)

    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "Research", "color": "#5875F7"}}
    )


class NoteFolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=20)
    sort_order: int | None = Field(default=None, ge=0)


class NoteFolderResponse(BaseModel):
    id: int
    name: str
    parent_id: int | None
    color: str | None
    sort_order: int
    note_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoteCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255, description="Note title")
    body: str = Field(default="", max_length=1_000_000, description="Markdown body")
    folder_id: int | None = Field(default=None, description="Folder to file the note under")
    tag_ids: list[int] = Field(default_factory=list, description="Tag IDs to associate")
    color: str | None = Field(default=None, max_length=20)
    is_pinned: bool = Field(default=False)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Project ideas",
                "body": "- Ship notes feature",
                "folder_id": 1,
                "tag_ids": [],
            }
        }
    )


class NoteUpdate(BaseModel):
    title: str | None = Field(
        default=None, max_length=255, description="Updated title; null to clear"
    )
    body: str | None = Field(
        default=None, max_length=1_000_000, description="Updated Markdown body"
    )
    folder_id: int | None = Field(
        default=None, description="Folder to file under; combine with clear_folder to un-file"
    )
    clear_folder: bool = Field(
        default=False, description="Set folder_id to None (un-file the note)"
    )
    tag_ids: list[int] | None = Field(default=None, description="Tag IDs; null to keep existing")
    is_pinned: bool | None = Field(default=None)
    color: str | None = Field(default=None, max_length=20)


class NotePageCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255, description="Page tab title")
    body: str = Field(default="", max_length=1_000_000, description="Markdown body")


class NotePageUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255, description="Set null to clear")
    body: str | None = Field(default=None, max_length=1_000_000)
    sort_order: int | None = Field(default=None, ge=0)


class NotePageReorderItem(BaseModel):
    id: int
    sort_order: int = Field(ge=0)


class NotePageReorder(BaseModel):
    items: list[NotePageReorderItem]


class NotePageResponse(BaseModel):
    id: int
    note_id: int
    title: str | None
    body: str
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoteResponse(BaseModel):
    id: int
    folder_id: int | None
    title: str | None
    body: str
    is_pinned: bool
    color: str | None
    is_encrypted: bool = False
    encrypted_at: datetime | None = None
    tags: list[TagBrief]
    pages: list[NotePageResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoteListResponse(BaseModel):
    items: list[NoteResponse]
    total: int
    offset: int
    limit: int
