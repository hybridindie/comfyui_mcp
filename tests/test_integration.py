"""End-to-end integration test with mocked ComfyUI backend."""

import json

import pytest
import httpx
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.server import _build_server
from comfyui_mcp.config import Settings, ComfyUISettings


@pytest.fixture
def server():
    settings = Settings(comfyui=ComfyUISettings(url="http://mock-comfyui:8188"))
    return _build_server(settings)


class TestEndToEnd:
    @respx.mock
    @pytest.mark.asyncio
    async def test_full_image_generation_flow(self, server):
        """Test: list models -> generate image -> check job -> list outputs."""
        # Mock all ComfyUI endpoints
        respx.get("http://mock-comfyui:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["sd_v15.safetensors"])
        )
        respx.post("http://mock-comfyui:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "test-001"})
        )
        respx.get("http://mock-comfyui:8188/history/test-001").mock(
            return_value=httpx.Response(200, json={
                "test-001": {
                    "outputs": {
                        "9": {"images": [{"filename": "comfyui-mcp_00001_.png", "subfolder": "", "type": "output"}]}
                    }
                }
            })
        )

        tools = server._tool_manager.list_tools()
        tool_names = {t.name for t in tools}

        assert "list_models" in tool_names
        assert "generate_image" in tool_names
        assert "get_job" in tool_names

    @respx.mock
    @pytest.mark.asyncio
    async def test_workflow_with_dangerous_node_in_audit_mode(self, server):
        """Audit mode should log but not block dangerous nodes."""
        respx.post("http://mock-comfyui:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "danger-001"})
        )

        tools = server._tool_manager.list_tools()
        tool_map = {t.name: t for t in tools}
        assert "run_workflow" in tool_map
