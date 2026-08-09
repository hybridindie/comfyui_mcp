"""Tests for /experiment/models metadata + preview endpoints (#143)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.settings import (
    register_settings_tools,  # noqa: F401  (ensure module load order)
)


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    sanitizer = PathSanitizer(allowed_extensions=[".safetensors", ".png"])
    return client, audit, limiter, sanitizer


class TestGetModelsWithMetadata:
    @respx.mock
    async def test_returns_enriched_listing(self, components):
        from comfyui_mcp.tools.discovery import register_discovery_tools

        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/experiment/models/checkpoints").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "name": "flux-dev.safetensors",
                        "pathIndex": 0,
                        "size": 11967221016,
                        "modified": 1715000000,
                    },
                    {
                        "name": "sd_xl.safetensors",
                        "pathIndex": 1,
                        "size": 6694700000,
                        "modified": 1714000000,
                    },
                ],
            )
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)
        result = await tools["comfyui_list_models_detailed"](folder="checkpoints")
        assert result["count"] == 2
        names = [m["name"] for m in result["models"]]
        assert "flux-dev.safetensors" in names
        assert result["models"][0]["pathIndex"] == 0


class TestGetModelPreview:
    @respx.mock
    async def test_returns_image_bytes(self, components):
        from comfyui_mcp.tools.discovery import register_discovery_tools

        client, audit, limiter, sanitizer = components
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        respx.get(
            "http://test:8188/experiment/models/preview/checkpoints/0/flux-dev.safetensors"
        ).mock(
            return_value=httpx.Response(
                200, content=png_bytes, headers={"content-type": "image/png"}
            )
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)
        result = await tools["comfyui_get_model_preview"](
            folder="checkpoints", path_index=0, filename="flux-dev.safetensors"
        )
        assert result["mime_type"] == "image/png"
        assert result["size_bytes"] == len(png_bytes)

    @respx.mock
    async def test_no_preview_returns_empty(self, components):
        from comfyui_mcp.tools.discovery import register_discovery_tools

        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/experiment/models/preview/checkpoints/0/none.safetensors").mock(
            return_value=httpx.Response(404, content=b"")
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)
        result = await tools["comfyui_get_model_preview"](
            folder="checkpoints", path_index=0, filename="none.safetensors"
        )
        assert result["available"] is False
