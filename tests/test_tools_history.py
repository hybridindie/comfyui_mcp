"""Tests for history MCP tools."""

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.tools.history import register_history_tools


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    return client, audit, limiter


class TestGetHistory:
    @respx.mock
    async def test_returns_paginated_envelope(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "def": {"outputs": {}}})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"]()
        assert result["total"] == 2
        assert result["offset"] == 0
        assert result["limit"] == 25
        assert result["has_more"] is False
        assert len(result["items"]) == 2
        # prompt_id should be injected into each entry
        prompt_ids = [item["prompt_id"] for item in result["items"]]
        assert "abc" in prompt_ids
        assert "def" in prompt_ids

    @respx.mock
    async def test_respects_limit_and_offset(self, components):
        client, audit, limiter = components
        history = {f"prompt_{i}": {"outputs": {}} for i in range(5)}
        respx.get("http://test:8188/history").mock(return_value=httpx.Response(200, json=history))
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"](limit=2, offset=0)
        assert len(result["items"]) == 2
        assert result["total"] == 5
        assert result["has_more"] is True

    @respx.mock
    async def test_handles_non_dict_entries(self, components):
        """Non-dict history values should be coerced, not crash."""
        client, audit, limiter = components
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "bad": "not-a-dict"})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"]()
        assert result["total"] == 2
        prompt_ids = [item["prompt_id"] for item in result["items"]]
        assert "abc" in prompt_ids
        assert "bad" in prompt_ids

    @respx.mock
    async def test_passes_1000_cap_to_client(self, components):
        # The tool should request up to 1000 history items from the client
        # so that pagination can report a meaningful `total` for callers paging
        # through history.
        client, audit, limiter = components
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        await tools["comfyui_get_history"]()
        request = route.calls.last.request
        params = dict(request.url.params.multi_items())
        assert params.get("max_items") == "1000"
