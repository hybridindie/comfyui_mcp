"""Tests for discovery MCP tools."""

import pytest
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.tools.discovery import register_discovery_tools
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.security.rate_limit import RateLimiter


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188", token="")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    return client, audit, limiter


class TestListModels:
    @respx.mock
    @pytest.mark.asyncio
    async def test_list_models_returns_models(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["v1.safetensors", "v2.safetensors"])
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter)

        result = await tools["list_models"](folder="checkpoints")
        assert "v1.safetensors" in result


class TestListNodes:
    @respx.mock
    @pytest.mark.asyncio
    async def test_list_nodes_returns_node_types(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {}, "CLIPTextEncode": {}})
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter)

        result = await tools["list_nodes"]()
        assert "KSampler" in result
        assert "CLIPTextEncode" in result
