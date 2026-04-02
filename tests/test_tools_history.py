"""Tests for history MCP tools."""

import json

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
        result = await tools["get_history"]()
        parsed = json.loads(result)
        assert parsed["total"] == 2
        assert parsed["offset"] == 0
        assert parsed["limit"] == 25
        assert parsed["has_more"] is False
        assert len(parsed["items"]) == 2
        # prompt_id should be injected into each entry
        prompt_ids = [item["prompt_id"] for item in parsed["items"]]
        assert "abc" in prompt_ids
        assert "def" in prompt_ids

    @respx.mock
    async def test_respects_limit_and_offset(self, components):
        client, audit, limiter = components
        history = {f"prompt_{i}": {"outputs": {}} for i in range(5)}
        respx.get("http://test:8188/history").mock(return_value=httpx.Response(200, json=history))
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["get_history"](limit=2, offset=0)
        parsed = json.loads(result)
        assert len(parsed["items"]) == 2
        assert parsed["total"] == 5
        assert parsed["has_more"] is True

    @respx.mock
    async def test_handles_non_dict_entries(self, components):
        """Non-dict history values should be coerced, not crash."""
        client, audit, limiter = components
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "bad": "not-a-dict"})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["get_history"]()
        parsed = json.loads(result)
        assert parsed["total"] == 2
        prompt_ids = [item["prompt_id"] for item in parsed["items"]]
        assert "abc" in prompt_ids
        assert "bad" in prompt_ids
