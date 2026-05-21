"""Plugin route handlers — install, uninstall, configure, hooks."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.plugin import PluginHookResponse, PluginInstall, PluginResponse
from app.services.plugin_manager import hook_manager
from app.services.plugin_service import PluginService

router = APIRouter(prefix="/api/v1/plugins", tags=["plugins"])


@router.post("", response_model=PluginResponse, status_code=201)
async def install_plugin(
    data: PluginInstall, db: AsyncSession = Depends(get_db)
) -> Any:
    """Install a new plugin."""
    svc = PluginService(db)
    return await svc.install(data)


@router.get("", response_model=list[PluginResponse])
async def list_plugins(db: AsyncSession = Depends(get_db)) -> Any:
    """List all installed plugins."""
    svc = PluginService(db)
    return await svc.list_all()


@router.get("/{plugin_id}", response_model=PluginResponse)
async def get_plugin(plugin_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get a specific plugin."""
    svc = PluginService(db)
    return await svc.get(plugin_id)


@router.delete("/{plugin_id}", status_code=204)
async def uninstall_plugin(plugin_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Uninstall a plugin and remove its hooks."""
    svc = PluginService(db)
    await svc.uninstall(plugin_id)


@router.post("/{plugin_id}/enable", response_model=PluginResponse)
async def enable_plugin(plugin_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Enable a plugin."""
    svc = PluginService(db)
    return await svc.enable(plugin_id)


@router.post("/{plugin_id}/disable", response_model=PluginResponse)
async def disable_plugin(plugin_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Disable a plugin."""
    svc = PluginService(db)
    return await svc.disable(plugin_id)


@router.get("/{plugin_id}/hooks", response_model=list[PluginHookResponse])
async def get_plugin_hooks(plugin_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    """Get all hooks registered by a plugin."""
    svc = PluginService(db)
    return await svc.get_hooks(plugin_id)


@router.get("/hooks/registry")
async def list_all_hooks() -> Any:
    """List all registered hooks across all plugins."""
    return hook_manager.get_hooks()
