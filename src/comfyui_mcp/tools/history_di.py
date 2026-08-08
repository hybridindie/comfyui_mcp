"""History tool (DI version) — module-level decorated function using Depends().

Phase 4 of the FastMCP 4 migration. Proof module: demonstrates the
module-level decorated-function pattern with Depends() for dependency
injection, replacing the register_history_tools() factory.

Per architecture.md rule 11, both patterns are valid. This module is opt-in:
server.py registers it via register() instead of the factory. The tool
surface (name, params, returns) is identical to the factory version.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.dependencies import Depends
from mcp.types import ToolAnnotations

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.dependencies import get_audit, get_client, get_read_limiter
from comfyui_mcp.pagination import LimitField, OffsetField
from comfyui_mcp.security.rate_limit import RateLimiter


async def _get_history_impl(
    limit: int,
    offset: int,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
) -> dict[str, Any]:
    """Shared implementation — callable directly with explicit deps (tests)
    or via Depends() resolution (framework). Kept separate so tests can call
    it without going through the MCP framework if needed."""
    # Fetch one extra entry so we can detect has_more without a second call.
    get_history_kwargs: dict[str, Any] = {"max_items": limit + 1}
    if offset > 0:
        get_history_kwargs["offset"] = offset
    raw = await client.get_history(**get_history_kwargs)

    entries = [{**(v if isinstance(v, dict) else {}), "prompt_id": k} for k, v in raw.items()]

    has_more = len(entries) > limit
    page = entries[:limit]
    count = len(page)
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


def register(mcp: FastMCP) -> None:
    """Register the DI-based history tool on a FastMCP server.

    Mirrors the register_*_tools() contract but takes no dependencies — they
    are resolved via Depends() at call time. server.py calls this once.
    """

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_history(
        limit: LimitField = 25,
        offset: OffsetField = 0,
        client: ComfyUIClient = Depends(get_client),
        audit: AuditLogger = Depends(get_audit),
        limiter: RateLimiter = Depends(get_read_limiter),
    ) -> dict[str, Any]:
        """Browse ComfyUI execution history (read-only).

        Uses server-side ``/history?offset=N&max_items=M`` so callers can page
        arbitrarily far back. The tool requests one extra entry per page so it
        can set ``has_more`` without an additional round-trip.

        Args:
            limit: Maximum number of results to return (default: 25, max: 100)
            offset: Zero-based starting index (default: 0)

        Returns:
            Envelope with keys ``items``, ``count`` (items in this page),
            ``offset``, ``limit``, ``has_more``, and ``total``.
        """
        return await _get_history_impl(limit, offset, client, audit, limiter)
