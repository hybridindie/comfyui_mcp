"""MCP resources: read-only ComfyUI state the LLM can browse without a tool call.

Resources complement the discovery tools — they let a client poll state by URI
instead of issuing a tool call. Templated resources (e.g. comfyui://models/{folder})
inherit FastMCP 4's built-in path-traversal screening, on by default.

Per architecture.md "Resources and prompts": resources are read-only. Mutating
operations stay as tools.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer


def _json_str(payload: dict[str, Any]) -> str:
    """Serialize a dict to a JSON string for resource return."""
    return json.dumps(payload, default=str)


def register_resources(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    sanitizer: PathSanitizer,
) -> dict[str, Any]:
    """Register read-only ComfyUI state resources.

    Returns a dict mapping resource keys to the underlying async functions so
    tests can call them directly (mirrors the register_*_tools() contract).
    """
    resource_fns: dict[str, Any] = {}

    @mcp.resource(
        "comfyui://models/{folder}",
        name="ComfyUI Models",
        description="List models in a ComfyUI folder (checkpoints, loras, vae, etc.).",
        mime_type="application/json",
    )
    async def comfyui_models_folder(folder: str) -> str:
        """List models in a folder. Path-traversal in {folder} is screened by FastMCP."""
        limiter.check("resource_models")
        sanitizer.validate_path_segment(folder, label="folder")
        await audit.async_log(tool="resource_models", action="called", extra={"folder": folder})
        models = await client.get_models(folder)
        return _json_str({"folder": folder, "models": models, "count": len(models)})

    resource_fns["comfyui_models_folder"] = comfyui_models_folder

    @mcp.resource(
        "comfyui://nodes/installed",
        name="ComfyUI Installed Nodes",
        description="Sorted list of all available ComfyUI node class types.",
        mime_type="application/json",
    )
    async def comfyui_installed_nodes() -> str:
        """Return a sorted list of available node class types from /object_info."""
        limiter.check("resource_nodes")
        await audit.async_log(tool="resource_nodes", action="called")
        info = await client.get_object_info()
        nodes = sorted(info.keys())
        return _json_str({"nodes": nodes, "count": len(nodes)})

    resource_fns["comfyui_installed_nodes"] = comfyui_installed_nodes

    @mcp.resource(
        "comfyui://queue",
        name="ComfyUI Queue",
        description="Current queue state: running and pending job counts.",
        mime_type="application/json",
    )
    async def comfyui_queue_state() -> str:
        """Return current queue running/pending counts from /queue."""
        limiter.check("resource_queue")
        await audit.async_log(tool="resource_queue", action="called")
        raw = await client.get_queue()
        running = len(raw.get("queue_running", []))
        pending = len(raw.get("queue_pending", []))
        return _json_str({"running": running, "pending": pending})

    resource_fns["comfyui_queue_state"] = comfyui_queue_state

    @mcp.resource(
        "comfyui://system",
        name="ComfyUI System Info",
        description="Whitelisted system info: ComfyUI version, GPU VRAM, queue counts.",
        mime_type="application/json",
    )
    async def comfyui_system_info() -> str:
        """Return whitelisted system info (GPU VRAM, queue counts, version only).

        Mirrors the comfyui_get_system_info tool whitelist — sensitive fields
        (hostname, OS, CPU, paths, Python version, network) are excluded.
        """
        limiter.check("resource_system")
        await audit.async_log(tool="resource_system", action="called")

        raw, queue_raw = await asyncio.gather(
            client.get_system_stats(),
            client.get_queue(),
        )

        devices: list[dict[str, Any]] = []
        for device in raw.get("devices", []):
            if not isinstance(device, dict):
                continue
            entry: dict[str, Any] = {}
            if "name" in device:
                entry["name"] = str(device["name"])
            vram_total = device.get("vram_total")
            vram_free = device.get("vram_free")
            if isinstance(vram_total, int | float):
                entry["vram_total_mb"] = round(vram_total / (1024 * 1024))
            if isinstance(vram_free, int | float):
                entry["vram_free_mb"] = round(vram_free / (1024 * 1024))
            if "torch_vram_total" in device and isinstance(device["torch_vram_total"], int | float):
                entry["torch_vram_total_mb"] = round(device["torch_vram_total"] / (1024 * 1024))
            if "torch_vram_free" in device and isinstance(device["torch_vram_free"], int | float):
                entry["torch_vram_free_mb"] = round(device["torch_vram_free"] / (1024 * 1024))
            if entry:
                devices.append(entry)

        running = len(queue_raw.get("queue_running", []))
        pending = len(queue_raw.get("queue_pending", []))

        result: dict[str, Any] = {
            "comfyui_version": str(raw.get("system", {}).get("comfyui_version", "unknown")),
            "devices": devices,
            "queue": {"running": running, "pending": pending},
        }
        return _json_str(result)

    resource_fns["comfyui_system_info"] = comfyui_system_info

    return resource_fns
