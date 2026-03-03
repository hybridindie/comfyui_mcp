"""Tests for ComfyUI HTTP client."""

import pytest
import httpx
import respx

from comfyui_mcp.client import ComfyUIClient


@pytest.fixture
def client():
    return ComfyUIClient(
        base_url="http://test-comfyui:8188",
        token="test-token",
        timeout_connect=5,
        timeout_read=10,
        tls_verify=False,
    )


class TestComfyUIClient:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_queue(self, client):
        respx.get("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        )
        result = await client.get_queue()
        assert "queue_running" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_prompt(self, client):
        respx.post("http://test-comfyui:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )
        result = await client.post_prompt({"1": {"class_type": "KSampler", "inputs": {}}})
        assert result["prompt_id"] == "abc-123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_header_sent(self, client):
        route = respx.get("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.get_queue()
        assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_auth_header_when_no_token(self):
        c = ComfyUIClient(base_url="http://test:8188", token="")
        route = respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await c.get_queue()
        assert "Authorization" not in route.calls[0].request.headers

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_models(self, client):
        respx.get("http://test-comfyui:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["model_v1.safetensors", "model_v2.safetensors"])
        )
        result = await client.get_models("checkpoints")
        assert len(result) == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_history(self, client):
        respx.get("http://test-comfyui:8188/history").mock(
            return_value=httpx.Response(200, json={"abc": {"outputs": {}}})
        )
        result = await client.get_history()
        assert "abc" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_object_info(self, client):
        respx.get("http://test-comfyui:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {"input": {}}})
        )
        result = await client.get_object_info()
        assert "KSampler" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_interrupt(self, client):
        respx.post("http://test-comfyui:8188/interrupt").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.interrupt()  # Should not raise

    @respx.mock
    @pytest.mark.asyncio
    async def test_upload_image(self, client):
        respx.post("http://test-comfyui:8188/upload/image").mock(
            return_value=httpx.Response(200, json={"name": "uploaded.png", "subfolder": "", "type": "input"})
        )
        result = await client.upload_image(b"fake-png-data", "test.png")
        assert result["name"] == "uploaded.png"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_image(self, client):
        respx.get("http://test-comfyui:8188/view").mock(
            return_value=httpx.Response(200, content=b"fake-image-bytes", headers={"content-type": "image/png"})
        )
        data, content_type = await client.get_image("output.png", "output")
        assert data == b"fake-image-bytes"
        assert content_type == "image/png"

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_queue_item(self, client):
        respx.post("http://test-comfyui:8188/queue").mock(
            return_value=httpx.Response(200, json={})
        )
        await client.delete_queue_item("abc-123")

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_history_item(self, client):
        respx.get("http://test-comfyui:8188/history/abc-123").mock(
            return_value=httpx.Response(200, json={"abc-123": {"outputs": {}}})
        )
        result = await client.get_history_item("abc-123")
        assert "abc-123" in result
