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
        url = progress._ws_url("client-1")
        assert url.startswith("ws://localhost:8188/ws?clientId=")
        assert "client-1" in url

    def test_ws_url_from_https(self):
        client = ComfyUIClient(base_url="https://gpu.example.com:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        url = progress._ws_url("client-2")
        assert url.startswith("wss://gpu.example.com:8188/ws?clientId=")
        assert "client-2" in url

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

    async def test_wait_for_completion_interrupted(self, monkeypatch):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=30.0)

        messages = [
            _make_ws_message("executing", {"node": "4"}),
            _make_ws_message(
                "execution_interrupted",
                {
                    "prompt_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "node_id": "4",
                },
            ),
        ]
        fake_ws = FakeWebSocket(messages)

        def fake_connect(url, **kwargs):
            return fake_ws

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fake_connect)

        state = await progress.wait_for_completion("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert state.status == "interrupted"

    async def test_wait_for_completion_with_events_captures_stream(self, monkeypatch):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=30.0)

        messages = [
            _make_ws_message("progress", {"value": 2, "max": 10}),
            _make_ws_message("executing", {"node": "3"}),
            _make_ws_message(
                "executed",
                {
                    "node": "9",
                    "output": {"images": [{"filename": "out.png", "subfolder": "output"}]},
                },
            ),
            _make_ws_message(
                "execution_success",
                {"prompt_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
            ),
        ]
        fake_ws = FakeWebSocket(messages)

        def fake_connect(url, **kwargs):
            return fake_ws

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fake_connect)

        state, events = await progress.wait_for_completion_with_events(
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        assert state.status == "completed"
        assert state.step == 2
        assert state.total_steps == 10
        assert state.outputs[0]["filename"] == "out.png"
        assert [event["type"] for event in events] == [
            "progress",
            "executing",
            "executed",
            "execution_success",
        ]

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

        # Simulate: first poll returns "in_progress", second returns "completed"
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        job_call_count = 0

        def job_side_effect(request):
            nonlocal job_call_count
            job_call_count += 1
            if job_call_count >= 2:
                return httpx.Response(
                    200,
                    json={
                        "id": prompt_id,
                        "status": "completed",
                        "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": ""}]}},
                    },
                )
            return httpx.Response(200, json={"id": prompt_id, "status": "in_progress"})

        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(side_effect=job_side_effect)

        # Patch sleep to avoid real delays in tests
        monkeypatch.setattr("comfyui_mcp.progress.asyncio.sleep", AsyncMock())

        state = await progress.wait_for_completion(prompt_id)
        assert state.status == "completed"
        assert state.elapsed_seconds is not None

    @respx.mock
    async def test_ws_failure_polling_terminates_on_cancelled(self, monkeypatch):
        """Regression: HTTP-polling fallback must treat 'interrupted' as terminal.

        Before the fix, _poll_until_complete only broke on 'completed'/'error',
        so a job that ended up cancelled would keep polling and return 'timeout'
        instead of 'interrupted'.
        """
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        def fail_connect(url, **kwargs):
            raise OSError("Connection refused")

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fail_connect)

        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(200, json={"id": prompt_id, "status": "cancelled"})
        )
        monkeypatch.setattr("comfyui_mcp.progress.asyncio.sleep", AsyncMock())

        state = await progress.wait_for_completion(prompt_id)
        assert state.status == "interrupted"

    @respx.mock
    async def test_get_state_http_fallback_completed(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": prompt_id,
                    "status": "completed",
                    "outputs": {"9": {"images": [{"filename": "img.png", "subfolder": "output"}]}},
                },
            )
        )

        state = await progress.get_state(prompt_id)
        assert state.status == "completed"
        assert len(state.outputs) == 1
        assert state.outputs[0]["filename"] == "img.png"

    @respx.mock
    async def test_get_state_http_fallback_queued(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={"id": prompt_id, "status": "pending"},
            )
        )
        # Queue is checked best-effort to derive a queue_position for pending jobs.
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(
                200,
                json={
                    "queue_running": [],
                    "queue_pending": [
                        [0, "other-id", {}, {}],
                        [1, prompt_id, {}, {}],
                    ],
                },
            )
        )

        state = await progress.get_state(prompt_id)
        assert state.status == "queued"
        assert state.queue_position == 2

    @respx.mock
    async def test_get_state_http_fallback_running(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={"id": prompt_id, "status": "in_progress"},
            )
        )

        state = await progress.get_state(prompt_id)
        assert state.status == "running"

    @respx.mock
    async def test_get_state_maps_failed_to_error(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={"id": prompt_id, "status": "failed"},
            )
        )

        state = await progress.get_state(prompt_id)
        assert state.status == "error"

    @respx.mock
    async def test_get_state_maps_cancelled_to_interrupted(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={"id": prompt_id, "status": "cancelled"},
            )
        )

        state = await progress.get_state(prompt_id)
        assert state.status == "interrupted"

    @respx.mock
    async def test_get_state_returns_unknown_on_404(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(404, json={"error": "Job not found"})
        )

        state = await progress.get_state(prompt_id)
        assert state.status == "unknown"

    @respx.mock
    async def test_preflight_history_check_avoids_hanging_on_fast_jobs(self, monkeypatch):
        """Jobs that complete before the WS connects must be caught by the pre-flight
        history check so _wait_internal returns immediately instead of hanging until
        the 300 s timeout (the race condition observed on the k3s cluster)."""
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=30.0)
        prompt_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # WS connects fine but sends no messages (job already done)
        fake_ws = FakeWebSocket([])

        def fake_connect(url, **kwargs):
            return fake_ws

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fake_connect)

        # /api/jobs/{id} immediately reports the job as completed
        respx.get(f"http://test:8188/api/jobs/{prompt_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": prompt_id,
                    "status": "completed",
                    "outputs": {"9": {"images": [{"filename": "fast.png", "subfolder": "output"}]}},
                },
            )
        )

        state, events = await progress.wait_for_completion_with_events(prompt_id)

        assert state.status == "completed"
        assert state.outputs[0]["filename"] == "fast.png"
        # Pre-flight path emits a marker event so callers know how it resolved
        assert any(e["type"] == "preflight_history" for e in events)
