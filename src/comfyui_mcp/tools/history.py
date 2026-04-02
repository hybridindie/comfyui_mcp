"""History tools: get_history."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

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

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def get_history() -> str:
        """Browse ComfyUI execution history (read-only)."""
        limiter.check("get_history")
        await audit.async_log(tool="get_history", action="called")
        return json.dumps(await client.get_history(max_items=200))

    tool_fns["get_history"] = get_history

    return tool_fns
