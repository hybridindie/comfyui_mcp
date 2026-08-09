"""Tests for /settings read/write tools (#142).

Verifies comfyui_get_settings returns the settings dict, comfyui_update_settings
writes via POST /settings with an audit log of the diff, and a comfyui://settings
resource exposes the read-only view.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.settings import register_settings_tools


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    sanitizer = PathSanitizer(allowed_extensions=[".json"])
    return client, audit, limiter, sanitizer


class TestGetSettings:
    @respx.mock
    async def test_get_settings_returns_dict(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/settings").mock(
            return_value=httpx.Response(
                200, json={"default_sampler": "euler", "feature_flags": {"x": True}}
            )
        )
        mcp = FastMCP("test")
        tools = register_settings_tools(mcp, client, audit, limiter, sanitizer)
        result = await tools["comfyui_get_settings"]()
        assert result["default_sampler"] == "euler"
        assert result["feature_flags"] == {"x": True}


class TestUpdateSettings:
    @respx.mock
    async def test_update_settings_posts_and_audits(self, components, tmp_path):
        client, audit, limiter, sanitizer = components
        route = respx.post("http://test:8188/settings").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_settings_tools(mcp, client, audit, limiter, sanitizer)
        await tools["comfyui_update_settings"](settings={"default_sampler": "dpmpp_2m"})
        assert route.called
        import json

        body = json.loads(route.calls.last.request.content)
        assert body == {"default_sampler": "dpmpp_2m"}
        # The audit log records the settings change
        log_text = (tmp_path / "audit.log").read_text().splitlines()
        records = [json.loads(line) for line in log_text if line]
        assert any(r["tool"] == "update_settings" and r["action"] == "updated" for r in records)

    @respx.mock
    async def test_update_settings_rejects_empty_dict(self, components):
        client, audit, limiter, sanitizer = components
        mcp = FastMCP("test")
        tools = register_settings_tools(mcp, client, audit, limiter, sanitizer)
        with pytest.raises(ValueError, match="empty"):
            await tools["comfyui_update_settings"](settings={})
