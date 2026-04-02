"""Tests for job management MCP tools."""

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.progress import WebSocketProgress
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.tools.jobs import register_job_tools


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    return client, audit, limiter


@pytest.fixture
def progress_components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    read_limiter = RateLimiter(max_per_minute=60)
    progress = WebSocketProgress(client, timeout=10.0)
    return client, audit, limiter, read_limiter, progress


class TestGetQueue:
    @respx.mock
    async def test_returns_queue_state(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={"queue_running": [["id1"]], "queue_pending": []})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_queue"]()
        assert "queue_running" in result


class TestCancelJob:
    @respx.mock
    async def test_cancel_job_sends_delete(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/queue").mock(return_value=httpx.Response(200, json={}))
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        await tools["comfyui_cancel_job"](prompt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert route.called


class TestInterrupt:
    @respx.mock
    async def test_interrupt_posts(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        await tools["comfyui_interrupt"]()
        assert route.called


class TestGetJob:
    @respx.mock
    async def test_get_job_returns_history_item(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/history/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").mock(
            return_value=httpx.Response(
                200,
                json={"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": {"outputs": {"9": {"images": []}}}},
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_job"](prompt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in result


class TestGetQueueStatus:
    @respx.mock
    async def test_get_queue_status_returns_exec_info(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"exec_info": {"queue_remaining": 5}})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_queue_status"]()
        assert "exec_info" in result


class TestClearQueue:
    @respx.mock
    async def test_clear_queue_pending(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/queue").mock(return_value=httpx.Response(200, json={}))
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_clear_queue"](clear_pending=True)
        assert "pending" in result.lower()
        assert route.called


class TestGetProgress:
    @respx.mock
    async def test_returns_completed_state(self, progress_components):
        client, audit, limiter, read_limiter, progress = progress_components
        respx.get("http://test:8188/history/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").mock(
            return_value=httpx.Response(
                200,
                json={
                    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": {
                        "outputs": {
                            "9": {"images": [{"filename": "out.png", "subfolder": "output"}]}
                        },
                        "status": {"completed": True},
                    }
                },
            )
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(
                200,
                json={
                    "queue_running": [],
                    "queue_pending": [],
                },
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(
            mcp,
            client,
            audit,
            limiter,
            read_limiter=read_limiter,
            progress=progress,
        )
        result = await tools["comfyui_get_progress"](
            prompt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        assert result["status"] == "completed"
        assert result["prompt_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert len(result["outputs"]) == 1

    @respx.mock
    async def test_returns_unknown_when_not_found(self, progress_components):
        client, audit, limiter, read_limiter, progress = progress_components
        not_found_id = "11111111-2222-3333-4444-555555555555"
        respx.get(f"http://test:8188/history/{not_found_id}").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(
                200,
                json={
                    "queue_running": [],
                    "queue_pending": [],
                },
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(
            mcp,
            client,
            audit,
            limiter,
            read_limiter=read_limiter,
            progress=progress,
        )
        result = await tools["comfyui_get_progress"](prompt_id=not_found_id)
        assert result["status"] == "unknown"
