"""Plugin hook system — HookManager with priority dispatch."""
from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class HookManager:
    """Manages plugin hooks with priority-ordered dispatch."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[tuple[int, Callable[..., Any]]]] = defaultdict(list)

    def register(self, hook_name: str, handler: Callable[..., Any], priority: int = 0) -> None:
        """Register a handler for a hook with given priority (lower = runs first)."""
        self._hooks[hook_name].append((priority, handler))
        self._hooks[hook_name].sort(key=lambda x: x[0])

    def unregister(self, hook_name: str, handler: Callable[..., Any]) -> None:
        """Remove a handler from a hook."""
        self._hooks[hook_name] = [
            (p, h) for p, h in self._hooks[hook_name] if h != handler
        ]

    async def dispatch(self, hook_name: str, *args: Any, **kwargs: Any) -> list[Any]:
        """Call all handlers for a hook in priority order. Returns list of results."""
        results = []
        for priority, handler in self._hooks.get(hook_name, []):
            try:
                result = handler(*args, **kwargs)
                # Support both sync and async handlers
                if hasattr(result, "__await__"):
                    result = await result
                results.append(result)
            except Exception as e:
                logger.error(f"Hook {hook_name} handler error: {e}")
        return results

    def get_hooks(self) -> dict[str, list[tuple[int, str]]]:
        """Return registered hooks for introspection."""
        return {
            name: [(p, h.__name__) for p, h in handlers]
            for name, handlers in self._hooks.items()
        }

    @staticmethod
    def load_handler(dotted_path: str) -> Callable[..., Any]:
        """Import and return a callable from a dotted path like 'module.path:function'."""
        if ":" in dotted_path:
            module_path, fn_name = dotted_path.rsplit(":", 1)
        else:
            module_path, fn_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        handler: Callable[..., Any] = getattr(module, fn_name)
        return handler


# Global hook manager
hook_manager = HookManager()
