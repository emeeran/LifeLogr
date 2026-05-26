"""Hello World example plugin for Diarilinux.

This plugin demonstrates how to write a Diarilinux plugin that:
1. Registers hooks for entry lifecycle events
2. Logs activity when entries are created or updated

## Plugin Structure

A plugin is a Python module with an ``entry_point`` that gets loaded
by the plugin manager. Hooks are registered via the ``hook_manager``.

## Installation

```bash
# Via API
curl -X POST /api/v1/plugins -d '{
    "name": "hello-world",
    "version": "1.0.0",
    "description": "Example plugin that greets on entry creation",
    "entry_point": "plugins.hello_world"
}'
```

## Available Hooks

| Hook Name | When Fired | Arguments |
|-----------|-----------|-----------|
| `entry.pre_create` | Before entry is saved | `data: EntryCreate` |
| `entry.post_create` | After entry is saved | `entry: Entry` |
| `entry.pre_update` | Before entry update | `entry: Entry, data: EntryUpdate` |
| `entry.post_update` | After entry update | `entry: Entry` |
| `entry.pre_delete` | Before soft-delete | `entry: Entry` |

## Writing Your Own Plugin

1. Create a Python module under ``plugins/`` or any installable package
2. Define handler functions (sync or async)
3. Register them with the ``hook_manager``
4. Install via the API with the module path as ``entry_point``
"""

from __future__ import annotations

import logging

logger = logging.getLogger("diarilinux.plugins.hello_world")

PLUGIN_NAME = "hello-world"
PLUGIN_VERSION = "1.0.0"


def on_entry_created(entry) -> str:
    """Called after a new entry is created."""
    logger.info(f"[HelloWorld] New entry created for {entry.entry_date}!")
    return f"Hello! Entry for {entry.entry_date} has been created."


def on_entry_updated(entry) -> str:
    """Called after an entry is updated."""
    logger.info(f"[HelloWorld] Entry {entry.id} updated.")
    return f"Entry {entry.id} was just updated."


async def on_entry_pre_create(data) -> None:
    """Called before an entry is saved — can modify data."""
    logger.info(f"[HelloWorld] About to create entry for {data.entry_date}")


def register_hooks() -> None:
    """Register all plugin hooks with the global hook manager.

    This function is called when the plugin is enabled.
    """
    from app.services.plugin_manager import hook_manager

    hook_manager.register("entry.post_create", on_entry_created, priority=10)
    hook_manager.register("entry.post_update", on_entry_updated, priority=10)
    hook_manager.register("entry.pre_create", on_entry_pre_create, priority=5)
    logger.info(f"[{PLUGIN_NAME}] Hooks registered.")


def unregister_hooks() -> None:
    """Remove all hooks when the plugin is disabled."""
    from app.services.plugin_manager import hook_manager

    hook_manager.unregister("entry.post_create", on_entry_created)
    hook_manager.unregister("entry.post_update", on_entry_updated)
    hook_manager.unregister("entry.pre_create", on_entry_pre_create)
    logger.info(f"[{PLUGIN_NAME}] Hooks unregistered.")
