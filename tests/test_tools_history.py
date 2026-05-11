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
    async def test_passes_limit_plus_one_to_client(self, components):
        """Tool requests one extra entry to detect has_more without an extra round-trip."""
        client, audit, limiter = components
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        await tools["comfyui_get_history"](limit=25)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["max_items"] == "26"

    @respx.mock
    async def test_passes_offset_to_client(self, components):
        client, audit, limiter = components
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        await tools["comfyui_get_history"](limit=10, offset=50)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["offset"] == "50"
        assert params["max_items"] == "11"

    @respx.mock
    async def test_omits_offset_when_zero(self, components):
        """offset=0 is the default and should not appear in the query string."""
        client, audit, limiter = components
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        await tools["comfyui_get_history"]()
        params = dict(route.calls.last.request.url.params.multi_items())
        assert "offset" not in params

    @respx.mock
    async def test_returns_envelope_with_known_total_on_last_page(self, components):
        """When the server returns <= limit entries we know we're on the last page;
        total is then the true count."""
        client, audit, limiter = components
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "def": {"outputs": {}}})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"](limit=25, offset=0)
        assert len(result["items"]) == 2
        assert result["count"] == 2
        assert result["offset"] == 0
        assert result["limit"] == 25
        assert result["has_more"] is False
        # Last page: total reflects the true running count (offset + count).
        assert result["total"] == 2

    @respx.mock
    async def test_has_more_true_when_extra_entry_returned(self, components):
        """If the server returns limit+1 entries, set has_more and drop the extra
        item from the page; total becomes None since the full count is unknown."""
        client, audit, limiter = components
        history = {f"prompt_{i}": {"outputs": {}} for i in range(6)}
        respx.get("http://test:8188/history").mock(return_value=httpx.Response(200, json=history))
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"](limit=5, offset=0)
        assert len(result["items"]) == 5
        assert result["count"] == 5
        assert result["has_more"] is True
        assert result["total"] is None

    @respx.mock
    async def test_injects_prompt_id_into_each_item(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "def": {"outputs": {}}})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"]()
        prompt_ids = sorted(item["prompt_id"] for item in result["items"])
        assert prompt_ids == ["abc", "def"]

    @respx.mock
    async def test_handles_non_dict_entries(self, components):
        """Non-dict history values are coerced to an empty dict shell + prompt_id."""
        client, audit, limiter = components
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "bad": "not-a-dict"})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"]()
        assert result["count"] == 2
        prompt_ids = sorted(item["prompt_id"] for item in result["items"])
        assert prompt_ids == ["abc", "bad"]

    @respx.mock
    async def test_empty_page_past_end_reports_unknown_total(self, components):
        """Paging past the end (offset>0, empty result): total is unknown, not offset.

        Regression for: if we just used `offset + count` we'd claim total=offset
        even though the true count is somewhere in [0, offset] — we can't tell.
        """
        client, audit, limiter = components
        respx.get("http://test:8188/history").mock(return_value=httpx.Response(200, json={}))
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"](limit=10, offset=5000)
        assert result["count"] == 0
        assert result["has_more"] is False
        assert result["total"] is None

    @respx.mock
    async def test_empty_history_at_offset_zero_reports_total_zero(self, components):
        """offset=0 with empty result means history is genuinely empty: total=0."""
        client, audit, limiter = components
        respx.get("http://test:8188/history").mock(return_value=httpx.Response(200, json={}))
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"](limit=10, offset=0)
        assert result["count"] == 0
        assert result["has_more"] is False
        assert result["total"] == 0

    @respx.mock
    async def test_deep_offset_supported(self, components):
        """Server-side offset means you can page past the previous 1000-item ceiling."""
        client, audit, limiter = components
        # Tool requests max_items=11 (limit + 1) starting at offset=5000.
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"deep": {"outputs": {}}})
        )
        mcp = FastMCP("test")
        tools = register_history_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_history"](limit=10, offset=5000)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["offset"] == "5000"
        # offset 5000 + count 1 → total 5001, has_more False since 1 ≤ limit
        assert result["count"] == 1
        assert result["offset"] == 5000
        assert result["has_more"] is False
        assert result["total"] == 5001
