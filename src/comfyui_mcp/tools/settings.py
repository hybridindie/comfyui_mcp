"""Settings tools: read/write ComfyUI server settings (#142).

Exposes /settings as comfyui_get_settings (read-only) and
comfyui_update_settings (mutating, audit-logged). The read path also backs
a comfyui://settings resource (registered in resources.py).
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer


def register_settings_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    sanitizer: PathSanitizer,
) -> dict[str, Any]:
    """Register settings tools and return callable functions for testing."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_settings() -> dict[str, Any]:
        """Read ComfyUI server settings (sampler defaults, UI prefs, feature flags).

        Returns the full settings dict as reported by GET /settings.
        """
        await audit.async_log(tool="get_settings", action="called")
        return await client.get_settings()

    tool_fns["comfyui_get_settings"] = comfyui_get_settings

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        )
    )
    async def comfyui_update_settings(
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge new settings into the ComfyUI server config via POST /settings.

        Mutating: the change is audit-logged with the full settings payload.
        Use comfyui_get_settings first to see what's currently set.

        Args:
            settings: A non-empty dict of settings to merge. Keys are setting
                      ids (e.g. "default_sampler"); values are the new values.
        """
        if not settings:
            raise ValueError("settings must be a non-empty dict")
        await client.update_settings(settings)
        await audit.async_log(
            tool="update_settings",
            action="updated",
            extra={"settings": settings},
        )
        return {"status": "updated", "settings": settings}

    tool_fns["comfyui_update_settings"] = comfyui_update_settings

    return tool_fns
