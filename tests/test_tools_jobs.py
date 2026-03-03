"""Tests for job management MCP tools."""

import pytest
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.tools.jobs import register_job_tools
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.security.rate_limit import RateLimiter


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188", token="")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    return client, audit, limiter


class TestGetQueue:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_queue_state(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={"queue_running": [["id1"]], "queue_pending": []})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["get_queue"]()
        assert "queue_running" in result


class TestCancelJob:
    @respx.mock
    @pytest.mark.asyncio
    async def test_cancel_job_sends_delete(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["cancel_job"](prompt_id="abc-123")
        assert route.called


class TestInterrupt:
    @respx.mock
    @pytest.mark.asyncio
    async def test_interrupt_posts(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        await tools["interrupt"]()
        assert route.called
