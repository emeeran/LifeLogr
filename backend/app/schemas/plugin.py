"""Pydantic schemas for plugin management."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_dotted_path(v: str) -> str:
    """Ensure entry_point is a safe Python dotted path (module[.path][:function])."""
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*(?::[a-zA-Z_][a-zA-Z0-9_]*)?$", v):
        raise ValueError(
            "entry_point must be in 'module.path' or 'module.path:function' format "
            "(alphanumeric, underscores, dots only)"
        )
    # Block access to dangerous modules
    module_path = v.split(":")[0]
    blocked = {"os", "sys", "subprocess", "shutil", "pathlib", "builtins", "importlib"}
    root_module = module_path.split(".")[0]
    if root_module in blocked:
        raise ValueError(f"Module '{root_module}' is not allowed for plugins")
    return v


class PluginInstall(BaseModel):
    """Install a new plugin."""

    name: str = Field(max_length=100)
    version: str = Field(max_length=20)
    description: str | None = Field(default=None, max_length=500)
    entry_point: str

    @field_validator("entry_point")
    @classmethod
    def validate_entry_point(cls, v: str) -> str:
        return _validate_dotted_path(v)


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
