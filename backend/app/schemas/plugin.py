"""Pydantic schemas for plugin management."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PluginInstall(BaseModel):
    """Install a new plugin."""
    name: str = Field(max_length=100)
    version: str = Field(max_length=20)
    description: str | None = Field(default=None, max_length=500)
    entry_point: str  # Python module path


class PluginResponse(BaseModel):
    """An installed plugin."""
    id: int
    name: str
    version: str
    description: str | None
    entry_point: str
    is_enabled: bool
    installed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PluginHookResponse(BaseModel):
    """A registered plugin hook."""
    id: int
    plugin_id: int
    hook_name: str
    handler_fn: str
    priority: int

    model_config = ConfigDict(from_attributes=True)
