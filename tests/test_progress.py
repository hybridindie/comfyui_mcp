"""Tests for WebSocket progress tracking."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import respx

from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.progress import ProgressState, WebSocketProgress


def _make_ws_message(msg_type: str, data: dict) -> str:
    """Helper to create ComfyUI WebSocket JSON message."""
    return json.dumps({"type": msg_type, "data": data})


class FakeWebSocket:
    """Fake WebSocket that yields pre-configured messages then closes."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        msg = self._messages[self._index]
        self._index += 1
        return msg

    async def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


class TestProgressState:
    def test_default_state(self):
        state = ProgressState(prompt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert state.prompt_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert state.status == "unknown"
        assert state.step is None
        assert state.total_steps is None
        assert state.current_node is None
        assert state.outputs == []

    def test_to_dict_omits_none_fields(self):
        state = ProgressState(
            prompt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", status="queued", queue_position=3
        )
        d = state.to_dict()
        assert d["prompt_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert d["status"] == "queued"
        assert d["queue_position"] == 3
        assert "step" not in d
        assert "total_steps" not in d
        assert "current_node" not in d

    def test_to_dict_includes_set_fields(self):
        state = ProgressState(
            prompt_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            status="running",
            step=5,
            total_steps=20,
            current_node="KSampler",
            elapsed_seconds=3.5,
        )
        d = state.to_dict()
        assert d["step"] == 5
        assert d["total_steps"] == 20
        assert d["current_node"] == "KSampler"
        assert d["elapsed_seconds"] == 3.5


class TestWebSocketProgress:
    def test_ws_url_from_http(self):
        client = ComfyUIClient(base_url="http://localhost:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        url = progress._ws_url()
        assert url.startswith("ws://localhost:8188/ws?clientId=")

    def test_ws_url_from_https(self):
        client = ComfyUIClient(base_url="https://gpu.example.com:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        url = progress._ws_url()
        assert url.startswith("wss://gpu.example.com:8188/ws?clientId=")

    async def test_wait_for_completion_success(self, monkeypatch):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=30.0)

        messages = [
            _make_ws_message("executing", {"node": "4"}),
            _make_ws_message("progress", {"value": 1, "max": 20}),
            _make_ws_message("progress", {"value": 20, "max": 20}),
            _make_ws_message(
                "executed",
                {
                    "node": "9",
                    "output": {"images": [{"filename": "out.png", "subfolder": "output"}]},
                },
            ),
            _make_ws_message("executing", {"node": None}),
        ]
        fake_ws = FakeWebSocket(messages)

        def fake_connect(url, **kwargs):
            return fake_ws

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fake_connect)

        state = await progress.wait_for_completion("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert state.status == "completed"
        assert state.step == 20
        assert state.total_steps == 20
        assert len(state.outputs) == 1
        assert state.outputs[0]["filename"] == "out.png"
        assert state.elapsed_seconds is not None
        assert state.elapsed_seconds >= 0

    async def test_wait_for_completion_error(self, monkeypatch):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=30.0)

        messages = [
            _make_ws_message("executing", {"node": "4"}),
            _make_ws_message(
                "execution_error",
                {
                    "exception_message": "Model not found",
                    "node_id": "4",
                },
            ),
        ]
        fake_ws = FakeWebSocket(messages)

        def fake_connect(url, **kwargs):
            return fake_ws

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fake_connect)

        state = await progress.wait_for_completion("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert state.status == "error"

    async def test_wait_for_completion_timeout(self, monkeypatch):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=0.1)

        class HangingWS:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.sleep(100)
                return ""

        def fake_connect(url, **kwargs):
            return HangingWS()

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fake_connect)

        state = await progress.wait_for_completion("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert state.status == "timeout"

    @respx.mock
    async def test_ws_failure_falls_back_to_http_polling(self, monkeypatch):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        def fail_connect(url, **kwargs):
            raise OSError("Connection refused")

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fail_connect)

        # Simulate: first poll returns "running", second returns "completed"
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        history_call_count = 0

        def history_side_effect(request):
            nonlocal history_call_count
            history_call_count += 1
            if history_call_count >= 2:
                return httpx.Response(
                    200,
                    json={
                        prompt_id: {
                            "outputs": {
                                "9": {"images": [{"filename": "out.png", "subfolder": ""}]}
                            },
                            "status": {"completed": True},
                        }
                    },
                )
            return httpx.Response(200, json={})

        respx.get(f"http://test:8188/history/{prompt_id}").mock(side_effect=history_side_effect)
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(
                200,
                json={
                    "queue_running": [["0", prompt_id, {}, {}]],
                    "queue_pending": [],
                },
            )
        )

        # Patch sleep to avoid real delays in tests
        monkeypatch.setattr("comfyui_mcp.progress.asyncio.sleep", AsyncMock())

        state = await progress.wait_for_completion(prompt_id)
        assert state.status == "completed"
        assert state.elapsed_seconds is not None

    @respx.mock
    async def test_get_state_http_fallback_completed(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        respx.get("http://test:8188/history/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").mock(
            return_value=httpx.Response(
                200,
                json={
                    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": {
                        "outputs": {
                            "9": {"images": [{"filename": "img.png", "subfolder": "output"}]}
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

        state = await progress.get_state("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert state.status == "completed"
        assert len(state.outputs) == 1
        assert state.outputs[0]["filename"] == "img.png"

    @respx.mock
    async def test_get_state_http_fallback_queued(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        respx.get("http://test:8188/history/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(
                200,
                json={
                    "queue_running": [],
                    "queue_pending": [
                        [0, "other-id", {}, {}],
                        [1, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", {}, {}],
                    ],
                },
            )
        )

        state = await progress.get_state("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert state.status == "queued"
        assert state.queue_position == 2

    @respx.mock
    async def test_get_state_http_fallback_running(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        respx.get("http://test:8188/history/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(
                200,
                json={
                    "queue_running": [[0, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", {}, {}]],
                    "queue_pending": [],
                },
            )
        )

        state = await progress.get_state("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert state.status == "running"
