"""Pydantic schemas for sync operations."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SyncQueueRequest(BaseModel):
    """Enqueue a sync operation."""
    operation: str = Field(pattern=r"^(create|update|delete)$")
    entity_type: str = Field(max_length=50)
    entity_id: int
    payload: dict


class SyncQueueResponse(BaseModel):
    """A queued sync operation."""
    id: int
    operation: str
    entity_type: str
    entity_id: int
    is_synced: bool
    created_at: datetime
    synced_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SyncStatusResponse(BaseModel):
    """Sync provider status."""
    provider: str
    last_sync_at: datetime | None
    status: str
    pending_count: int

    model_config = ConfigDict(from_attributes=True)


class SyncFlushResponse(BaseModel):
    """Result of a sync flush."""
    synced: int
    provider: str


class CloudSyncRequest(BaseModel):
    """Request for cloud push/pull."""
    provider: str = Field(default="local")
    passphrase: str | None = None


class CloudSyncResponse(BaseModel):
    """Result of cloud sync operation."""
    pushed: int | None = None
    pulled: int | None = None
    provider: str
