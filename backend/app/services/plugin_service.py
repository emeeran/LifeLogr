"""PluginService — install, uninstall, enable/disable, lifecycle management."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.plugin import Plugin, PluginHook
from app.schemas.plugin import PluginInstall
from app.services.plugin_manager import hook_manager

logger = logging.getLogger(__name__)


class PluginService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def install(self, data: PluginInstall) -> Plugin:
        """Install a new plugin."""
        plugin = Plugin(
            name=data.name,
            version=data.version,
            description=data.description,
            entry_point=data.entry_point,
        )
        self.db.add(plugin)
        await self.db.commit()
        await self.db.refresh(plugin)
        return plugin

    async def uninstall(self, plugin_id: int) -> None:
        """Uninstall a plugin and remove all its hooks."""
        plugin = await self.get(plugin_id)

        # Remove hooks from DB
        result = await self.db.execute(select(PluginHook).where(PluginHook.plugin_id == plugin_id))
        for hook in result.scalars().all():
            # Unregister from hook manager
            try:
                handler = hook_manager.load_handler(hook.handler_fn)
                hook_manager.unregister(hook.hook_name, handler)
            except Exception as e:
                logger.warning(
                    "Failed to unregister hook %s during plugin cleanup: %s", hook.hook_name, e
                )
            await self.db.delete(hook)

        await self.db.delete(plugin)
        await self.db.commit()

    async def get(self, plugin_id: int) -> Plugin:
        result = await self.db.execute(select(Plugin).where(Plugin.id == plugin_id))
        plugin = result.scalar_one_or_none()
        if not plugin:
            raise NotFoundError(f"Plugin {plugin_id} not found")
        return plugin

    async def list_all(self) -> list[Plugin]:
        result = await self.db.execute(select(Plugin).order_by(Plugin.name))
        return list(result.scalars().all())

    async def enable(self, plugin_id: int) -> Plugin:
        plugin = await self.get(plugin_id)
        plugin.is_enabled = True
        await self.db.commit()
        await self.db.refresh(plugin)
        return plugin

    async def disable(self, plugin_id: int) -> Plugin:
        plugin = await self.get(plugin_id)
        plugin.is_enabled = False
        await self.db.commit()
        await self.db.refresh(plugin)
        return plugin

    async def get_hooks(self, plugin_id: int) -> list[PluginHook]:
        await self.get(plugin_id)  # verify exists
        result = await self.db.execute(select(PluginHook).where(PluginHook.plugin_id == plugin_id))
        return list(result.scalars().all())
