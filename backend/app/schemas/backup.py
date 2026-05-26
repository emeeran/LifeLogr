"""Pydantic schemas for backup config and snapshots."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BackupConfigCreate(BaseModel):
    provider: str = Field(description="One of: google_drive, onedrive, dropbox, webdav, nas")
    credentials: dict[str, str] = Field(description="Provider-specific credential map")
    schedule_cron: str | None = Field(default=None, description="Cron expression for auto-backup")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider": "webdav",
                "credentials": {
                    "url": "https://dav.example.com",
                    "username": "user",
                    "password": "***",
                },
                "schedule_cron": "0 3 * * *",
            }
        }
    )


class BackupConfigResponse(BaseModel):
    id: int
    provider: str
    schedule_cron: str | None
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BackupSnapshotResponse(BaseModel):
    id: int
    config_id: int
    status: str
    entries_synced: int
    media_synced: int
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None

    model_config = ConfigDict(from_attributes=True)


class RestoreRequest(BaseModel):
    config_id: int
