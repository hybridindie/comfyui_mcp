"""History tools: get_history."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.pagination import LimitField, OffsetField, paginate
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
    async def comfyui_get_history(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> dict[str, Any]:
        """Browse ComfyUI execution history (read-only).

        Covers up to the 1000 most recent history entries — older entries are
        unreachable. Pagination operates over that window.

        Args:
            limit: Maximum number of results to return (default: 25, max: 100)
            offset: Starting index for pagination (default: 0)
        """
        limiter.check("get_history")
        await audit.async_log(tool="get_history", action="called")
        raw = await client.get_history(max_items=1000)
        entries = [{**(v if isinstance(v, dict) else {}), "prompt_id": k} for k, v in raw.items()]
        return paginate(entries, offset, limit, default_limit=25, max_limit=100)

    tool_fns["comfyui_get_history"] = comfyui_get_history

    return tool_fns
