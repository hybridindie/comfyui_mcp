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

            ``total`` is set only when we can prove the true count:

            - ``offset + count`` on the last page when ``count > 0``
              (the upstream returned at most ``limit`` entries, so we've seen
              everything from ``offset`` onward).
            - ``0`` when ``offset == 0`` and the upstream returned nothing
              (history is genuinely empty).
            - ``None`` otherwise (``has_more`` is True, OR we paged past the
              end and got back an empty result — in the latter case the true
              count is somewhere in ``[0, offset]`` and we can't tell which).

            ``has_more`` is the canonical end-of-history signal.
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
        # ``total`` is the true count when we can prove it. Three branches:
        #   - has_more=True: we don't know the upper end. total = None.
        #   - count > 0 and not has_more: this is the last page with data;
        #     true total is offset + count.
        #   - count == 0 with offset > 0: we paged past the end. True total
        #     is unknown (the upstream just returns empty; it could be
        #     anywhere from 0 to offset). total = None.
        #   - count == 0 with offset == 0: history is genuinely empty.
        total: int | None
        if has_more or (count == 0 and offset > 0):  # noqa: SIM108
            total = None
        else:
            total = offset + count

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
