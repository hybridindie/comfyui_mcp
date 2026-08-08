"""Tests for the history MCP tool (DI version — history_di).

The factory version (history.py) was removed in #138; these tests now drive
the module-level DI tool through mcp.call_tool, which resolves the
Depends() dependencies. Pagination edge-case coverage is preserved.
"""

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.dependencies import configure_dependencies, reset_dependencies
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.model_checker import ModelChecker
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools import history_di


@pytest.fixture
def configured(tmp_path):
    """Wire dependencies with test doubles and register the DI tool."""
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    configure_dependencies(
        client=client,
        audit=audit,
        inspector=WorkflowInspector(mode="audit", dangerous_nodes=[], allowed_nodes=[]),
        sanitizer=PathSanitizer(allowed_extensions=[".png"]),
        model_checker=ModelChecker(),
        read_limiter=RateLimiter(max_per_minute=60),
        workflow_limiter=RateLimiter(max_per_minute=60),
        generation_limiter=RateLimiter(max_per_minute=60),
        file_limiter=RateLimiter(max_per_minute=60),
    )
    mcp = FastMCP("test")
    history_di.register(mcp)
    yield client, mcp
    reset_dependencies()


async def _call(mcp, **kwargs):
    """Call comfyui_get_history via the framework so Depends() resolves."""
    result = await mcp.call_tool("comfyui_get_history", kwargs)
    assert result.is_error is False, result
    return result.structured_content


class TestGetHistory:
    @respx.mock
    async def test_passes_limit_plus_one_to_client(self, configured):
        """Tool requests one extra entry to detect has_more without an extra round-trip."""
        _client, mcp = configured
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        await _call(mcp, limit=25)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["max_items"] == "26"

    @respx.mock
    async def test_passes_offset_to_client(self, configured):
        _client, mcp = configured
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        await _call(mcp, limit=10, offset=50)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["offset"] == "50"
        assert params["max_items"] == "11"

    @respx.mock
    async def test_omits_offset_when_zero(self, configured):
        """offset=0 is the default and should not appear in the query string."""
        _client, mcp = configured
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={})
        )
        await _call(mcp)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert "offset" not in params

    @respx.mock
    async def test_returns_envelope_with_known_total_on_last_page(self, configured):
        """When the server returns <= limit entries we know we're on the last page;
        total is then the true count."""
        _client, mcp = configured
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "def": {"outputs": {}}})
        )
        result = await _call(mcp, limit=25, offset=0)
        assert len(result["items"]) == 2
        assert result["count"] == 2
        assert result["offset"] == 0
        assert result["limit"] == 25
        assert result["has_more"] is False
        assert result["total"] == 2

    @respx.mock
    async def test_has_more_true_when_extra_entry_returned(self, configured):
        """If the server returns limit+1 entries, set has_more and drop the extra
        item from the page; total becomes None since the full count is unknown."""
        _client, mcp = configured
        history = {f"prompt_{i}": {"outputs": {}} for i in range(6)}
        respx.get("http://test:8188/history").mock(return_value=httpx.Response(200, json=history))
        result = await _call(mcp, limit=5, offset=0)
        assert len(result["items"]) == 5
        assert result["count"] == 5
        assert result["has_more"] is True
        assert result["total"] is None

    @respx.mock
    async def test_injects_prompt_id_into_each_item(self, configured):
        _client, mcp = configured
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "def": {"outputs": {}}})
        )
        result = await _call(mcp)
        prompt_ids = sorted(item["prompt_id"] for item in result["items"])
        assert prompt_ids == ["abc", "def"]

    @respx.mock
    async def test_handles_non_dict_entries(self, configured):
        """Non-dict history values are coerced to an empty dict shell + prompt_id."""
        _client, mcp = configured
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "bad": "not-a-dict"})
        )
        result = await _call(mcp)
        assert result["count"] == 2
        prompt_ids = sorted(item["prompt_id"] for item in result["items"])
        assert prompt_ids == ["abc", "bad"]

    @respx.mock
    async def test_empty_page_past_end_reports_unknown_total(self, configured):
        """Paging past the end (offset>0, empty result): total is unknown, not offset."""
        _client, mcp = configured
        respx.get("http://test:8188/history").mock(return_value=httpx.Response(200, json={}))
        result = await _call(mcp, limit=10, offset=5000)
        assert result["count"] == 0
        assert result["has_more"] is False
        assert result["total"] is None

    @respx.mock
    async def test_empty_history_at_offset_zero_reports_total_zero(self, configured):
        """offset=0 with empty result means history is genuinely empty: total=0."""
        _client, mcp = configured
        respx.get("http://test:8188/history").mock(return_value=httpx.Response(200, json={}))
        result = await _call(mcp, limit=10, offset=0)
        assert result["count"] == 0
        assert result["has_more"] is False
        assert result["total"] == 0

    @respx.mock
    async def test_deep_offset_supported(self, configured):
        """Server-side offset means you can page past the previous 1000-item ceiling."""
        _client, mcp = configured
        route = respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"deep": {"outputs": {}}})
        )
        result = await _call(mcp, limit=10, offset=5000)
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["offset"] == "5000"
        assert result["count"] == 1
        assert result["offset"] == 5000
        assert result["has_more"] is False
        assert result["total"] == 5001
