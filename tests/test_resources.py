"""Tests for MCP resources (read-only ComfyUI state browsing)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.resources import register_resources
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer, PathValidationError

_ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".safetensors"]


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    sanitizer = PathSanitizer(allowed_extensions=_ALLOWED_EXTENSIONS)
    return client, audit, limiter, sanitizer


class TestModelsResource:
    @respx.mock
    async def test_models_folder_returns_list(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["v1.safetensors", "v2.safetensors"])
        )
        mcp = FastMCP("test")
        fns = register_resources(mcp, client, audit, limiter, sanitizer)

        result = await fns["comfyui_models_folder"]("checkpoints")
        assert isinstance(result, str)
        import json

        data = json.loads(result)
        assert data["models"] == ["v1.safetensors", "v2.safetensors"]
        assert data["count"] == 2
        assert data["folder"] == "checkpoints"

    @respx.mock
    async def test_models_folder_empty(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/models/loras").mock(return_value=httpx.Response(200, json=[]))
        mcp = FastMCP("test")
        fns = register_resources(mcp, client, audit, limiter, sanitizer)

        result = await fns["comfyui_models_folder"]("loras")
        import json

        data = json.loads(result)
        assert data["models"] == []
        assert data["count"] == 0

    @respx.mock
    async def test_models_folder_rejects_traversal(self, components):
        client, audit, limiter, sanitizer = components
        mcp = FastMCP("test")
        fns = register_resources(mcp, client, audit, limiter, sanitizer)

        # Path traversal in the folder segment must be rejected before the
        # handler runs (FastMCP 4 screens templated resource params by default).
        with pytest.raises(PathValidationError):
            await fns["comfyui_models_folder"]("../etc/passwd")


class TestNodesResource:
    @respx.mock
    async def test_installed_nodes_returns_sorted_list(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {}, "CLIPTextEncode": {}})
        )
        mcp = FastMCP("test")
        fns = register_resources(mcp, client, audit, limiter, sanitizer)

        result = await fns["comfyui_installed_nodes"]()
        import json

        data = json.loads(result)
        assert data["nodes"] == ["CLIPTextEncode", "KSampler"]
        assert data["count"] == 2


class TestQueueResource:
    @respx.mock
    async def test_queue_returns_running_and_pending(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(
                200,
                json={
                    "queue_running": [{"prompt_id": "r1"}],
                    "queue_pending": [{"prompt_id": "p1"}, {"prompt_id": "p2"}],
                },
            )
        )
        mcp = FastMCP("test")
        fns = register_resources(mcp, client, audit, limiter, sanitizer)

        result = await fns["comfyui_queue_state"]()
        import json

        data = json.loads(result)
        assert data["running"] == 1
        assert data["pending"] == 2


class TestSystemResource:
    @respx.mock
    async def test_system_returns_whitelisted_fields(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/system_stats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "system": {"comfyui_version": "0.3.0", "hostname": "secret-host"},
                    "devices": [
                        {
                            "name": "cuda:0",
                            "vram_total": 8589934592,
                            "vram_free": 4294967296,
                        }
                    ],
                },
            )
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        )
        mcp = FastMCP("test")
        fns = register_resources(mcp, client, audit, limiter, sanitizer)

        result = await fns["comfyui_system_info"]()
        import json

        data = json.loads(result)
        assert data["comfyui_version"] == "0.3.0"
        assert data["devices"][0]["vram_total_mb"] == 8192
        assert "hostname" not in data
        assert "system" not in data


class TestRegistration:
    async def test_register_resources_returns_callable_dict(self, components):
        client, audit, limiter, sanitizer = components
        mcp = FastMCP("test")
        fns = register_resources(mcp, client, audit, limiter, sanitizer)
        assert isinstance(fns, dict)
        assert "comfyui_models_folder" in fns
        assert "comfyui_installed_nodes" in fns
        assert "comfyui_queue_state" in fns
        assert "comfyui_system_info" in fns
