"""Discovery tools: list_models, list_nodes, get_node_info, list_workflows."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter


def register_discovery_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
) -> dict[str, Any]:
    """Register discovery tools and return a dict of callable functions for testing."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool()
    async def list_models(folder: str = "checkpoints") -> list[str]:
        """List available models in a folder (checkpoints, loras, vae, etc.)."""
        limiter.check("list_models")
        audit.log(tool="list_models", action="called", extra={"folder": folder})
        return await client.get_models(folder)

    tool_fns["list_models"] = list_models

    @mcp.tool()
    async def list_nodes() -> list[str]:
        """List all available ComfyUI node types."""
        limiter.check("list_nodes")
        audit.log(tool="list_nodes", action="called")
        info = await client.get_object_info()
        return sorted(info.keys())

    tool_fns["list_nodes"] = list_nodes

    @mcp.tool()
    async def get_node_info(node_class: str) -> dict:
        """Get detailed information about a specific node type."""
        limiter.check("get_node_info")
        audit.log(tool="get_node_info", action="called", extra={"node_class": node_class})
        return await client.get_object_info(node_class)

    tool_fns["get_node_info"] = get_node_info

    @mcp.tool()
    async def list_workflows() -> list:
        """List available workflow templates."""
        limiter.check("list_workflows")
        audit.log(tool="list_workflows", action="called")
        return await client.get_workflow_templates()

    tool_fns["list_workflows"] = list_workflows

    return tool_fns
