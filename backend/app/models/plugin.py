"""Plugin and PluginHook ORM models — plugin architecture."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Plugin(Base):
    """Installed plugins."""
    __tablename__ = "plugins"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    entry_point: Mapped[str] = mapped_column(String, nullable=False)  # Python module path
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    installed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class PluginHook(Base):
    """Registered hooks for plugins."""
    __tablename__ = "plugin_hooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    plugin_id: Mapped[int] = mapped_column(Integer, nullable=False)
    hook_name: Mapped[str] = mapped_column(String(100), nullable=False)
    handler_fn: Mapped[str] = mapped_column(String, nullable=False)  # dotted path to callable
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
