"""Tests for the DI-based history tool (Depends() proof module, Phase 4).

Verifies the module-level decorated tool resolves its dependencies
(client, audit, limiter) via Depends() when called through the MCP
framework, and that the tool surface (name, params, returns) is unchanged
from the factory version.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.dependencies import configure_dependencies, reset_dependencies
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.tools import history_di


@pytest.fixture
def configured(tmp_path):
    """Wire dependencies with test doubles."""
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    read_limiter = RateLimiter(max_per_minute=60)
    workflow_limiter = RateLimiter(max_per_minute=10)
    generation_limiter = RateLimiter(max_per_minute=10)
    file_limiter = RateLimiter(max_per_minute=30)
    from comfyui_mcp.security.inspector import WorkflowInspector
    from comfyui_mcp.security.model_checker import ModelChecker
    from comfyui_mcp.security.sanitizer import PathSanitizer

    configure_dependencies(
        client=client,
        audit=audit,
        inspector=WorkflowInspector(mode="audit", dangerous_nodes=[], allowed_nodes=[]),
        sanitizer=PathSanitizer(allowed_extensions=[".png"]),
        model_checker=ModelChecker(),
        read_limiter=read_limiter,
        workflow_limiter=workflow_limiter,
        generation_limiter=generation_limiter,
        file_limiter=file_limiter,
    )
    yield client
    reset_dependencies()


class TestGetHistoryDI:
    @respx.mock
    async def test_resolves_dependencies_via_depends(self, configured):
        """The module-level tool resolves client/audit/limiter via Depends()
        when called through mcp.call_tool() — no factory needed."""
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}})
        )
        mcp = FastMCP("test")
        history_di.register(mcp)
        result = await mcp.call_tool("comfyui_get_history", {"limit": 25, "offset": 0})
        assert result.is_error is False
        assert result.structured_content["count"] == 1
        assert result.structured_content["total"] == 1

    @respx.mock
    async def test_surface_unchanged_returns_envelope(self, configured):
        """The tool's return shape is identical to the factory version."""
        respx.get("http://test:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}, "def": {"outputs": {}}})
        )
        mcp = FastMCP("test")
        history_di.register(mcp)
        result = await mcp.call_tool("comfyui_get_history", {"limit": 25})
        sc = result.structured_content
        assert set(sc.keys()) == {"items", "count", "offset", "limit", "has_more", "total"}
        assert sc["count"] == 2
        assert sc["has_more"] is False

    @respx.mock
    async def test_schema_excludes_dependencies(self, configured):
        """Depends() params (client, audit, limiter) must NOT appear in the
        tool's input schema — only limit and offset."""
        mcp = FastMCP("test")
        history_di.register(mcp)
        tools = await mcp.list_tools()
        tool = next(t for t in tools if t.name == "comfyui_get_history")
        schema_props = set(tool.parameters.get("properties", {}).keys())
        assert schema_props == {"limit", "offset"}


class TestProviderMisconfiguration:
    async def test_provider_raises_when_unconfigured(self, tmp_path):
        """A provider called before configure_dependencies() fails loud."""
        reset_dependencies()
        from comfyui_mcp.dependencies import get_client

        with pytest.raises(RuntimeError, match="Dependencies not configured"):
            get_client()
