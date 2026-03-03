"""History tools: get_history, get_history_item."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter


def register_history_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
) -> dict[str, Any]:
    """Register history tools and return callable functions for testing."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool()
    async def get_history() -> dict:
        """Browse ComfyUI execution history (read-only)."""
        limiter.check("get_history")
        audit.log(tool="get_history", action="called")
        return await client.get_history()

    tool_fns["get_history"] = get_history

    @mcp.tool()
    async def get_history_item(prompt_id: str) -> dict:
        """Get details of a specific history entry by prompt_id."""
        limiter.check("get_history_item")
        audit.log(tool="get_history_item", action="called", extra={"prompt_id": prompt_id})
        return await client.get_history_item(prompt_id)

    tool_fns["get_history_item"] = get_history_item

    return tool_fns
