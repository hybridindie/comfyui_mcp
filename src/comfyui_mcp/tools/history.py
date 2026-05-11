"""History tools: get_history."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.pagination import LimitField, OffsetField
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

        Uses server-side `/history?offset=N&max_items=M` so callers can page
        arbitrarily far back. The tool requests one extra entry per page so it
        can set ``has_more`` without an additional round-trip.

        Args:
            limit: Maximum number of results to return (default: 25, max: 100)
            offset: Zero-based starting index (default: 0)

        Returns:
            Envelope with keys ``items``, ``count`` (items in this page),
            ``offset``, ``limit``, ``has_more``, and ``total``.

            ``total`` is set only when we know the true count — i.e., on the
            last page (when fewer than ``limit + 1`` entries came back). On
            non-last pages ``total`` is ``None`` because the upstream endpoint
            does not return a count separately and computing it would require
            fetching every entry.
        """
        limiter.check("get_history")
        await audit.async_log(
            tool="get_history", action="called", extra={"limit": limit, "offset": offset}
        )

        # Fetch one extra entry so we can detect has_more without a second call.
        # max_items is capped to 1000 by the client; for limit=100 that's 101,
        # well under the cap. The offset kwarg is omitted when 0 to keep the
        # request URL identical to historical behavior for the common case.
        get_history_kwargs: dict[str, Any] = {"max_items": limit + 1}
        if offset > 0:
            get_history_kwargs["offset"] = offset
        raw = await client.get_history(**get_history_kwargs)

        entries = [{**(v if isinstance(v, dict) else {}), "prompt_id": k} for k, v in raw.items()]

        has_more = len(entries) > limit
        page = entries[:limit]
        count = len(page)
        # On the last page (no extra entry came back) the true total is the
        # number we've seen so far; otherwise we can't know it cheaply.
        total: int | None = (offset + count) if not has_more else None

        return {
            "items": page,
            "count": count,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "total": total,
        }

    tool_fns["comfyui_get_history"] = comfyui_get_history

    return tool_fns
