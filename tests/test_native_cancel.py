"""Tests for native /api/jobs/{id}/cancel + batch cancel (#141).

Verifies the native jobs-cancel endpoint is used with a fallback to the
legacy /queue delete on 404 (older ComfyUI builds), and the new batch
cancel tool works.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.tools.jobs import register_job_tools


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    return client, audit, limiter


class TestCancelJobNative:
    @respx.mock
    async def test_uses_native_jobs_cancel_when_available(self, components):
        """When /api/jobs/{id}/cancel returns 200, cancel_job uses it (not
        the legacy /queue delete)."""
        client, audit, limiter = components
        native = respx.post(
            "http://test:8188/api/jobs/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/cancel"
        ).mock(return_value=httpx.Response(200, json={"cancelled": True}))
        legacy = respx.post("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        await tools["comfyui_cancel_job"](prompt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert native.called
        assert not legacy.called, "legacy /queue delete should not be called when native succeeds"

    @respx.mock
    async def test_falls_back_to_legacy_queue_delete_on_404(self, components):
        """When /api/jobs/{id}/cancel returns 404 (older ComfyUI), cancel_job
        falls back to the legacy /queue delete."""
        client, audit, limiter = components
        respx.post("http://test:8188/api/jobs/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/cancel").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        legacy = respx.post("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        await tools["comfyui_cancel_job"](prompt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert legacy.called, "should fall back to legacy /queue delete on 404"


class TestCancelJobsBatch:
    @respx.mock
    async def test_batch_cancel_posts_job_ids(self, components):
        """comfyui_cancel_jobs (batch) POSTs job_ids to /api/jobs/cancel."""
        client, audit, limiter = components
        route = respx.post("http://test:8188/api/jobs/cancel").mock(
            return_value=httpx.Response(200, json={"cancelled": 2})
        )
        mcp = FastMCP("test")
        tools = register_job_tools(mcp, client, audit, limiter)
        result = await tools["comfyui_cancel_jobs"](job_ids=["job-1", "job-2"])
        assert route.called
        import json

        body = json.loads(route.calls.last.request.content)
        assert body["job_ids"] == ["job-1", "job-2"]
        assert "cancelled" in str(result)
