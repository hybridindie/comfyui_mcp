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
    async def test_interrupt_global(self, components):
        client, audit, limiter = components
        route = respx.post("http://test:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_interrupt"]()
        assert route.called
        body = route.calls.last.request.content
        # No prompt_id sent → no body, or empty
        assert body in (b"", b"{}", None)
        assert "current" in result.lower() or "global" in result.lower()

    @respx.mock
    async def test_interrupt_targeted(self, components):
        import json as _json

        client, audit, limiter = components
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        route = respx.post("http://test:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_interrupt"](prompt_id=prompt_id)
        assert route.called
        body = _json.loads(route.calls.last.request.content)
        assert body == {"prompt_id": prompt_id}
        assert prompt_id in result


class TestGetJob:
    @respx.mock
    async def test_get_job_returns_unified_job_object(self, components):
        # Upstream returns the prompt id as "id" — see comfy_execution/jobs.py.
        client, audit, limiter = components
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": prompt_id,
                    "status": "in_progress",
                    "outputs": {},
                },
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_get_job"](prompt_id=prompt_id)
        assert result["id"] == prompt_id
        assert result["status"] == "in_progress"


class TestListJobs:
    @respx.mock
    async def test_list_jobs_default(self, components):
        client, audit, limiter = components
        respx.get("http://test:8188/api/jobs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [{"id": "abc", "status": "completed"}],
                    "pagination": {"offset": 0, "limit": None, "total": 1, "has_more": False},
                },
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_list_jobs"]()
        assert "jobs" in result
        assert "pagination" in result
        assert result["jobs"][0]["status"] == "completed"

    @respx.mock
    async def test_list_jobs_passes_filters(self, components):
        client, audit, limiter = components
        route = respx.get("http://test:8188/api/jobs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [],
                    "pagination": {"offset": 0, "limit": 5, "total": 0, "has_more": False},
                },
            )
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        await tools["comfyui_list_jobs"](
            status=["pending", "in_progress"],
            sort_by="execution_duration",
            sort_order="asc",
            limit=5,
            offset=0,
        )
        params = dict(route.calls.last.request.url.params.multi_items())
        assert params["status"] == "pending,in_progress"
        assert params["sort_by"] == "execution_duration"
        assert params["sort_order"] == "asc"
        assert params["limit"] == "5"


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
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": prompt_id,
                    "status": "completed",
                    "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "output"}]}},
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
        result = await tools["comfyui_get_progress"](prompt_id=prompt_id)
        assert result["status"] == "completed"
        assert result["prompt_id"] == prompt_id
        assert len(result["outputs"]) == 1

    @respx.mock
    async def test_returns_unknown_when_not_found(self, progress_components):
        client, audit, limiter, read_limiter, progress = progress_components
        not_found_id = "11111111-2222-3333-4444-555555555555"
        respx.get(f"http://test:8188/api/jobs/{not_found_id}").mock(
            return_value=httpx.Response(404, json={"error": "Job not found"})
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
