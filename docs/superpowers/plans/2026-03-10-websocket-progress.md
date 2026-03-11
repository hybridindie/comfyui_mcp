# WebSocket Progress Tracking Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time progress tracking for workflow execution via ComfyUI's WebSocket API, with a `wait` parameter on `run_workflow`/`generate_image` and a new `get_progress` tool.

**Architecture:** On-demand WebSocket connections to ComfyUI's `/ws` endpoint with HTTP fallback. New `progress.py` module manages WebSocket lifecycle and state buffering. Tools layer gains `wait` bool parameter and `get_progress` tool.

**Tech Stack:** websockets>=15.0, httpx (existing), asyncio

**Spec:** `docs/superpowers/specs/2026-03-10-websocket-progress-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/comfyui_mcp/progress.py` | `ProgressState` dataclass, `WebSocketProgress` class (WS connect, event parsing, state buffering, HTTP fallback) |
| Modify | `src/comfyui_mcp/client.py:10-23` | Expose `base_url` property for WebSocket URL derivation |
| Modify | `pyproject.toml:7-12` | Add `websockets>=15.0` dependency |
| Modify | `src/comfyui_mcp/tools/generation.py:144-186` | Add `progress` kwarg to `register_generation_tools`, `wait` param to `run_workflow` and `generate_image` |
| Modify | `src/comfyui_mcp/tools/jobs.py:14-19` | Add `progress` and `read_limiter` kwargs to `register_job_tools`, add `get_progress` tool |
| Modify | `src/comfyui_mcp/server.py:67-89` | Wire `WebSocketProgress` into tool registration |
| Create | `tests/test_progress.py` | Unit tests for `ProgressState`, `WebSocketProgress` |
| Modify | `tests/test_tools_generation.py` | Tests for `wait=True` on `run_workflow` and `generate_image` |
| Modify | `tests/test_tools_jobs.py` | Tests for `get_progress` tool |

---

### Task 1: Add websockets dependency

**Files:**
- Modify: `pyproject.toml:7-12`

- [ ] **Step 1: Add websockets to dependencies**

In `pyproject.toml`, add `"websockets>=15.0"` to the `dependencies` list:

```toml
dependencies = [
    "mcp[cli]>=1.12.0",
    "httpx>=0.28.0",
    "pydantic>=2.10.0",
    "pyyaml>=6.0.0",
    "websockets>=15.0",
]
```

- [ ] **Step 2: Install dependencies**

Run: `uv sync`
Expected: succeeds, websockets installed

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add websockets dependency for progress tracking"
```

---

### Task 2: Create progress module with ProgressState and WebSocketProgress

**Files:**
- Create: `src/comfyui_mcp/progress.py`
- Modify: `src/comfyui_mcp/client.py:10-23`
- Create: `tests/test_progress.py`

**Context:** `ComfyUIClient` stores `self._base_url` (private). We need to expose it for WebSocket URL derivation. The WebSocket URL scheme must be translated: `http://` → `ws://`, `https://` → `wss://`.

ComfyUI WebSocket protocol sends JSON messages:
- `{type: "progress", data: {value: 5, max: 20}}` — sampling step
- `{type: "executing", data: {node: "3"}}` — node running (null node = done)
- `{type: "executed", data: {node: "7", output: {images: [...]}}}` — node output
- `{type: "execution_error", data: {...}}` — error

- [ ] **Step 1: Expose base_url on ComfyUIClient**

In `src/comfyui_mcp/client.py`, add a property after `__init__` (after line 23):

```python
@property
def base_url(self) -> str:
    return self._base_url
```

- [ ] **Step 2: Write failing tests for ProgressState**

Create `tests/test_progress.py`:

```python
"""Tests for WebSocket progress tracking."""

from __future__ import annotations

from comfyui_mcp.progress import ProgressState


class TestProgressState:
    def test_default_state(self):
        state = ProgressState(prompt_id="abc-123")
        assert state.prompt_id == "abc-123"
        assert state.status == "unknown"
        assert state.step is None
        assert state.total_steps is None
        assert state.current_node is None
        assert state.outputs == []

    def test_to_dict_omits_none_fields(self):
        state = ProgressState(prompt_id="abc-123", status="queued", queue_position=3)
        d = state.to_dict()
        assert d["prompt_id"] == "abc-123"
        assert d["status"] == "queued"
        assert d["queue_position"] == 3
        assert "step" not in d
        assert "total_steps" not in d
        assert "current_node" not in d

    def test_to_dict_includes_set_fields(self):
        state = ProgressState(
            prompt_id="abc-123",
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
```

Run: `uv run pytest tests/test_progress.py -v`
Expected: FAIL — `comfyui_mcp.progress` does not exist

- [ ] **Step 3: Implement ProgressState**

Create `src/comfyui_mcp/progress.py`:

```python
"""WebSocket progress tracking for ComfyUI workflow execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets

from comfyui_mcp.client import ComfyUIClient


@dataclass
class ProgressState:
    """Unified progress state for a workflow execution."""

    prompt_id: str
    status: str = "unknown"
    queue_position: int | None = None
    current_node: str | None = None
    step: int | None = None
    total_steps: int | None = None
    elapsed_seconds: float | None = None
    outputs: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, omitting None fields."""
        d: dict[str, Any] = {"prompt_id": self.prompt_id, "status": self.status}
        if self.queue_position is not None:
            d["queue_position"] = self.queue_position
        if self.current_node is not None:
            d["current_node"] = self.current_node
        if self.step is not None:
            d["step"] = self.step
        if self.total_steps is not None:
            d["total_steps"] = self.total_steps
        if self.elapsed_seconds is not None:
            d["elapsed_seconds"] = self.elapsed_seconds
        if self.outputs:
            d["outputs"] = self.outputs
        return d
```

Run: `uv run pytest tests/test_progress.py::TestProgressState -v`
Expected: PASS (3 tests)

- [ ] **Step 4: Write failing tests for WebSocketProgress**

Add to `tests/test_progress.py`:

```python
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
            _make_ws_message("executed", {
                "node": "9",
                "output": {"images": [{"filename": "out.png", "subfolder": "output"}]},
            }),
            _make_ws_message("executing", {"node": None}),
        ]
        fake_ws = FakeWebSocket(messages)

        def fake_connect(url, **kwargs):
            return fake_ws

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fake_connect)

        state = await progress.wait_for_completion("prompt-1")
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
            _make_ws_message("execution_error", {
                "exception_message": "Model not found",
                "node_id": "4",
            }),
        ]
        fake_ws = FakeWebSocket(messages)

        def fake_connect(url, **kwargs):
            return fake_ws

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fake_connect)

        state = await progress.wait_for_completion("prompt-1")
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

        state = await progress.wait_for_completion("prompt-1")
        assert state.status == "timeout"

    @respx.mock
    async def test_ws_failure_falls_back_to_http_polling(self, monkeypatch):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        def fail_connect(url, **kwargs):
            raise OSError("Connection refused")

        monkeypatch.setattr("comfyui_mcp.progress.websockets.connect", fail_connect)

        # Simulate: first poll returns "running", second returns "completed"
        history_call_count = 0

        def history_side_effect(request):
            nonlocal history_call_count
            history_call_count += 1
            if history_call_count >= 2:
                return httpx.Response(200, json={
                    "prompt-1": {
                        "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": ""}]}},
                        "status": {"completed": True},
                    }
                })
            return httpx.Response(200, json={})

        respx.get("http://test:8188/history/prompt-1").mock(
            side_effect=history_side_effect
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={
                "queue_running": [["0", "prompt-1", {}, {}]],
                "queue_pending": [],
            })
        )

        # Patch sleep to avoid real delays in tests
        monkeypatch.setattr("comfyui_mcp.progress.asyncio.sleep", AsyncMock())

        state = await progress.wait_for_completion("prompt-1")
        assert state.status == "completed"
        assert state.elapsed_seconds is not None

    @respx.mock
    async def test_get_state_http_fallback_completed(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        respx.get("http://test:8188/history/abc-123").mock(
            return_value=httpx.Response(200, json={
                "abc-123": {
                    "outputs": {
                        "9": {"images": [{"filename": "img.png", "subfolder": "output"}]}
                    },
                    "status": {"completed": True},
                }
            })
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={
                "queue_running": [],
                "queue_pending": [],
            })
        )

        state = await progress.get_state("abc-123")
        assert state.status == "completed"
        assert len(state.outputs) == 1
        assert state.outputs[0]["filename"] == "img.png"

    @respx.mock
    async def test_get_state_http_fallback_queued(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        respx.get("http://test:8188/history/abc-123").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={
                "queue_running": [],
                "queue_pending": [
                    [0, "other-id", {}, {}],
                    [1, "abc-123", {}, {}],
                ],
            })
        )

        state = await progress.get_state("abc-123")
        assert state.status == "queued"
        assert state.queue_position == 2

    @respx.mock
    async def test_get_state_http_fallback_running(self):
        client = ComfyUIClient(base_url="http://test:8188")
        progress = WebSocketProgress(client, timeout=10.0)

        respx.get("http://test:8188/history/abc-123").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={
                "queue_running": [[0, "abc-123", {}, {}]],
                "queue_pending": [],
            })
        )

        state = await progress.get_state("abc-123")
        assert state.status == "running"
```

Run: `uv run pytest tests/test_progress.py -v`
Expected: FAIL — `WebSocketProgress` not defined

- [ ] **Step 5: Implement WebSocketProgress**

Add to `src/comfyui_mcp/progress.py` (after `ProgressState`):

```python
class WebSocketProgress:
    """Manages on-demand WebSocket connections for progress tracking."""

    def __init__(self, client: ComfyUIClient, timeout: float = 300.0) -> None:
        self._client = client
        self._timeout = timeout
        self._client_id = uuid.uuid4().hex

    def _ws_url(self) -> str:
        """Derive WebSocket URL from client's HTTP base URL."""
        base = self._client.base_url
        if base.startswith("https://"):
            ws_base = "wss://" + base[len("https://"):]
        else:
            ws_base = "ws://" + base[len("http://"):]
        return f"{ws_base}/ws?clientId={self._client_id}"

    async def wait_for_completion(self, prompt_id: str) -> ProgressState:
        """Connect via WebSocket and block until the prompt completes, errors, or times out."""
        state = ProgressState(prompt_id=prompt_id, status="running")
        start_time = time.monotonic()

        try:
            async with asyncio.timeout(self._timeout):
                async with websockets.connect(self._ws_url()) as ws:
                    async for raw_msg in ws:
                        if isinstance(raw_msg, bytes):
                            continue
                        msg = json.loads(raw_msg)
                        msg_type = msg.get("type")
                        data = msg.get("data", {})

                        # Filter events by prompt_id — ComfyUI sends
                        # events for all jobs on the same connection
                        event_prompt_id = data.get("prompt_id")
                        if event_prompt_id is not None and event_prompt_id != prompt_id:
                            continue

                        if msg_type == "progress":
                            state.step = data.get("value")
                            state.total_steps = data.get("max")

                        elif msg_type == "executing":
                            node = data.get("node")
                            if node is None:
                                # null node means execution finished
                                state.status = "completed"
                                break
                            state.current_node = node

                        elif msg_type == "executed":
                            output = data.get("output", {})
                            for key in ("images", "gifs"):
                                for item in output.get(key, []):
                                    state.outputs.append({
                                        "node_id": data.get("node", ""),
                                        "filename": item.get("filename", ""),
                                        "subfolder": item.get("subfolder", ""),
                                    })

                        elif msg_type == "execution_error":
                            state.status = "error"
                            break

        except TimeoutError:
            state.status = "timeout"
        except (OSError, websockets.exceptions.WebSocketException):
            # WebSocket failed — fall back to HTTP polling per spec
            return await self._poll_until_complete(prompt_id, start_time)

        state.elapsed_seconds = round(time.monotonic() - start_time, 2)
        return state

    async def _poll_until_complete(
        self, prompt_id: str, start_time: float
    ) -> ProgressState:
        """Poll HTTP endpoints until completion or timeout."""
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= self._timeout:
                state = ProgressState(prompt_id=prompt_id, status="timeout")
                state.elapsed_seconds = round(elapsed, 2)
                return state
            state = await self.get_state(prompt_id)
            if state.status in ("completed", "error"):
                state.elapsed_seconds = round(time.monotonic() - start_time, 2)
                return state
            await asyncio.sleep(1.0)

    async def get_state(self, prompt_id: str) -> ProgressState:
        """Get current state via HTTP fallback (queue + history)."""
        state = ProgressState(prompt_id=prompt_id)

        # Check history first (completed jobs)
        with contextlib.suppress(httpx.HTTPError, OSError):
            history = await self._client.get_history_item(prompt_id)
            if prompt_id in history:
                state.status = "completed"
                entry = history[prompt_id]
                outputs = entry.get("outputs", {})
                for _node_id, node_output in outputs.items():
                    for key in ("images", "gifs"):
                        for item in node_output.get(key, []):
                            state.outputs.append({
                                "node_id": _node_id,
                                "filename": item.get("filename", ""),
                                "subfolder": item.get("subfolder", ""),
                            })
                return state

        # Check queue (running/pending)
        with contextlib.suppress(httpx.HTTPError, OSError):
            queue = await self._client.get_queue()
            for item in queue.get("queue_running", []):
                if len(item) >= 2 and item[1] == prompt_id:
                    state.status = "running"
                    return state
            pending = queue.get("queue_pending", [])
            for i, item in enumerate(pending):
                if len(item) >= 2 and item[1] == prompt_id:
                    state.status = "queued"
                    state.queue_position = i + 1
                    return state

        return state
```

Run: `uv run pytest tests/test_progress.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Run linters**

Run: `uv run ruff check src/comfyui_mcp/progress.py tests/test_progress.py && uv run ruff format --check src/comfyui_mcp/progress.py tests/test_progress.py && uv run mypy src/comfyui_mcp/progress.py`
Expected: PASS (fix any issues)

- [ ] **Step 7: Commit**

```bash
git add src/comfyui_mcp/client.py src/comfyui_mcp/progress.py tests/test_progress.py
git commit -m "feat: add WebSocketProgress module for real-time execution tracking"
```

---

### Task 3: Add get_progress tool to jobs.py

**Files:**
- Modify: `src/comfyui_mcp/tools/jobs.py:14-19`
- Modify: `tests/test_tools_jobs.py`

**Context:** `register_job_tools` currently takes `(mcp, client, audit, limiter)`. We need to add `progress` and `read_limiter` kwargs. The existing `limiter` (workflow category) stays for mutation tools. `get_progress` uses `read_limiter`.

- [ ] **Step 1: Write failing test for get_progress**

Add to `tests/test_tools_jobs.py`:

```python
import json

from comfyui_mcp.progress import WebSocketProgress

# Update the existing components fixture to also provide progress + read_limiter:

@pytest.fixture
def progress_components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    read_limiter = RateLimiter(max_per_minute=60)
    progress = WebSocketProgress(client, timeout=10.0)
    return client, audit, limiter, read_limiter, progress


class TestGetProgress:
    @respx.mock
    async def test_returns_completed_state(self, progress_components):
        client, audit, limiter, read_limiter, progress = progress_components
        respx.get("http://test:8188/history/abc-123").mock(
            return_value=httpx.Response(200, json={
                "abc-123": {
                    "outputs": {
                        "9": {"images": [{"filename": "out.png", "subfolder": "output"}]}
                    },
                    "status": {"completed": True},
                }
            })
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={
                "queue_running": [],
                "queue_pending": [],
            })
        )
        mcp = FastMCP("test")
        tools = register_job_tools(
            mcp, client, audit, limiter,
            read_limiter=read_limiter, progress=progress,
        )
        result = await tools["get_progress"](prompt_id="abc-123")
        data = json.loads(result)
        assert data["status"] == "completed"
        assert data["prompt_id"] == "abc-123"
        assert len(data["outputs"]) == 1

    @respx.mock
    async def test_returns_unknown_when_not_found(self, progress_components):
        client, audit, limiter, read_limiter, progress = progress_components
        respx.get("http://test:8188/history/nope").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.get("http://test:8188/queue").mock(
            return_value=httpx.Response(200, json={
                "queue_running": [],
                "queue_pending": [],
            })
        )
        mcp = FastMCP("test")
        tools = register_job_tools(
            mcp, client, audit, limiter,
            read_limiter=read_limiter, progress=progress,
        )
        result = await tools["get_progress"](prompt_id="nope")
        data = json.loads(result)
        assert data["status"] == "unknown"
```

Run: `uv run pytest tests/test_tools_jobs.py::TestGetProgress -v`
Expected: FAIL — `register_job_tools` doesn't accept `read_limiter`/`progress` kwargs

- [ ] **Step 2: Update register_job_tools signature and add get_progress**

Modify `src/comfyui_mcp/tools/jobs.py`:

Update the import block to add:
```python
import json

from comfyui_mcp.progress import WebSocketProgress
```

Update the function signature (line 14-19):
```python
def register_job_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    *,
    read_limiter: RateLimiter | None = None,
    progress: WebSocketProgress | None = None,
) -> dict[str, Any]:
```

Add the `get_progress` tool before `return tool_fns`:
```python
    @mcp.tool()
    async def get_progress(prompt_id: str) -> str:
        """Get the current execution progress for a workflow.

        Returns status (queued/running/completed/error/unknown), step progress,
        current node, queue position, and output files when available.

        Args:
            prompt_id: The prompt_id returned by run_workflow or generate_image.
        """
        progress_limiter = read_limiter if read_limiter is not None else limiter
        progress_limiter.check("get_progress")
        audit.log(tool="get_progress", action="called", extra={"prompt_id": prompt_id})
        if progress is None:
            return json.dumps({"prompt_id": prompt_id, "status": "unknown",
                              "error": "Progress tracking not configured"})
        state = await progress.get_state(prompt_id)
        return json.dumps(state.to_dict())

    tool_fns["get_progress"] = get_progress
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `uv run pytest tests/test_tools_jobs.py -v`
Expected: PASS (all existing tests + new tests)

- [ ] **Step 4: Run linters**

Run: `uv run ruff check src/comfyui_mcp/tools/jobs.py tests/test_tools_jobs.py && uv run mypy src/comfyui_mcp/tools/jobs.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/tools/jobs.py tests/test_tools_jobs.py
git commit -m "feat: add get_progress tool for workflow execution tracking"
```

---

### Task 4: Add wait parameter to run_workflow

**Files:**
- Modify: `src/comfyui_mcp/tools/generation.py:144-186`
- Modify: `tests/test_tools_generation.py`

**Context:** `register_generation_tools` already takes `read_limiter` kwarg. We add `progress` kwarg. `run_workflow` gets `wait: bool = False`. When `wait=True`, it calls `progress.wait_for_completion()` after submission and returns structured JSON. When `wait=False`, current behavior is unchanged.

- [ ] **Step 1: Write failing tests for wait=True**

Add to `tests/test_tools_generation.py`:

```python
from comfyui_mcp.progress import WebSocketProgress


@pytest.fixture
def progress_components(tmp_path, monkeypatch):
    """Components with progress tracking enabled."""
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    inspector = WorkflowInspector(
        mode="audit",
        dangerous_nodes=["EvalNode"],
        allowed_nodes=[],
    )
    progress = WebSocketProgress(client, timeout=10.0)
    return client, audit, limiter, inspector, progress, monkeypatch


class TestRunWorkflowWait:
    @respx.mock
    async def test_wait_true_returns_structured_result(self, progress_components):
        client, audit, limiter, inspector, progress, monkeypatch = progress_components
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "wait-123"})
        )

        from comfyui_mcp.progress import ProgressState

        async def fake_wait(prompt_id):
            return ProgressState(
                prompt_id=prompt_id,
                status="completed",
                elapsed_seconds=5.2,
                outputs=[{"node_id": "9", "filename": "out.png", "subfolder": "output"}],
            )

        monkeypatch.setattr(progress, "wait_for_completion", fake_wait)

        mcp_server = FastMCP("test")
        tools = register_generation_tools(
            mcp_server, client, audit, limiter, inspector, progress=progress,
        )
        result = await tools["run_workflow"](
            workflow=json.dumps({"1": {"class_type": "KSampler", "inputs": {}}}),
            wait=True,
        )
        data = json.loads(result)
        assert data["prompt_id"] == "wait-123"
        assert data["status"] == "completed"
        assert data["elapsed_seconds"] == 5.2
        assert len(data["outputs"]) == 1

    @respx.mock
    async def test_wait_false_returns_prompt_id_string(self, progress_components):
        client, audit, limiter, inspector, progress, _ = progress_components
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "nowait-456"})
        )
        mcp_server = FastMCP("test")
        tools = register_generation_tools(
            mcp_server, client, audit, limiter, inspector, progress=progress,
        )
        result = await tools["run_workflow"](
            workflow=json.dumps({"1": {"class_type": "KSampler", "inputs": {}}}),
            wait=False,
        )
        assert "nowait-456" in result
        # Should be plain string, not JSON
        assert not result.startswith("{")
```

Run: `uv run pytest tests/test_tools_generation.py::TestRunWorkflowWait -v`
Expected: FAIL — `run_workflow` doesn't accept `wait` param

- [ ] **Step 2: Update register_generation_tools and run_workflow**

In `src/comfyui_mcp/tools/generation.py`:

Add import:
```python
from comfyui_mcp.progress import WebSocketProgress
```

Update `register_generation_tools` signature to add `progress` kwarg:
```python
def register_generation_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    inspector: WorkflowInspector,
    *,
    read_limiter: RateLimiter | None = None,
    progress: WebSocketProgress | None = None,
) -> dict[str, Any]:
```

Update `run_workflow` to accept `wait` parameter and handle both paths.

**Important:** In the existing `run_workflow` function, rename `result = inspector.inspect(wf)` to `inspection = inspector.inspect(wf)`, and update all references: `result.nodes_used` → `inspection.nodes_used`, `result.warnings` → `inspection.warnings`. This avoids shadowing with the new `result_dict` variable. The full updated function:

```python
    @mcp.tool()
    async def run_workflow(workflow: str, wait: bool = False) -> str:
        """Submit an arbitrary ComfyUI workflow for execution.

        Args:
            workflow: JSON string of a ComfyUI workflow (API format).
                      Each key is a node ID, each value has 'class_type' and 'inputs'.
            wait: If True, block until execution completes and return structured result
                  with status, outputs, and elapsed time. If False (default), return
                  immediately with just the prompt_id.
        """
        limiter.check("run_workflow")
        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e

        # Inspect the workflow
        inspection = inspector.inspect(wf)
        audit.log(
            tool="run_workflow",
            action="inspected",
            nodes_used=inspection.nodes_used,
            warnings=inspection.warnings,
            status="allowed",
        )

        warning_msg = _format_warnings(inspection.warnings)

        # Submit to ComfyUI
        response = await client.post_prompt(wf)
        prompt_id = response.get("prompt_id", "unknown")
        audit.log(tool="run_workflow", action="submitted", prompt_id=prompt_id)

        if wait and progress is not None:
            state = await progress.wait_for_completion(prompt_id)
            audit.log(
                tool="run_workflow",
                action="completed",
                prompt_id=prompt_id,
                extra={"status": state.status, "elapsed": state.elapsed_seconds},
            )
            result_dict = state.to_dict()
            if inspection.warnings:
                result_dict["warnings"] = inspection.warnings
            return json.dumps(result_dict)

        return f"Workflow submitted. prompt_id: {prompt_id}{warning_msg}"
```

- [ ] **Step 3: Verify all generation tests pass**

Run: `uv run pytest tests/test_tools_generation.py -v`
Expected: PASS (all existing + new tests)

- [ ] **Step 4: Run linters**

Run: `uv run ruff check src/comfyui_mcp/tools/generation.py && uv run mypy src/comfyui_mcp/tools/generation.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py
git commit -m "feat: add wait parameter to run_workflow for blocking execution"
```

---

### Task 5: Add wait parameter to generate_image

**Files:**
- Modify: `src/comfyui_mcp/tools/generation.py:190-237`
- Modify: `tests/test_tools_generation.py`

**Context:** Same pattern as `run_workflow` — add `wait: bool = False` param. When `wait=True`, call `progress.wait_for_completion()` after submission.

- [ ] **Step 1: Write failing test**

Add to `tests/test_tools_generation.py`:

```python
class TestGenerateImageWait:
    @respx.mock
    async def test_wait_true_returns_structured_result(self, progress_components):
        client, audit, limiter, inspector, progress, monkeypatch = progress_components
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "img-wait-1"})
        )

        from comfyui_mcp.progress import ProgressState

        async def fake_wait(prompt_id):
            return ProgressState(
                prompt_id=prompt_id,
                status="completed",
                elapsed_seconds=12.3,
                outputs=[{"node_id": "9", "filename": "cat.png", "subfolder": "output"}],
            )

        monkeypatch.setattr(progress, "wait_for_completion", fake_wait)

        mcp_server = FastMCP("test")
        tools = register_generation_tools(
            mcp_server, client, audit, limiter, inspector, progress=progress,
        )
        result = await tools["generate_image"](prompt="a cat", wait=True)
        data = json.loads(result)
        assert data["prompt_id"] == "img-wait-1"
        assert data["status"] == "completed"
        assert len(data["outputs"]) == 1

    @respx.mock
    async def test_wait_false_returns_prompt_id_string(self, progress_components):
        client, audit, limiter, inspector, progress, _ = progress_components
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "img-nowait"})
        )
        mcp_server = FastMCP("test")
        tools = register_generation_tools(
            mcp_server, client, audit, limiter, inspector, progress=progress,
        )
        result = await tools["generate_image"](prompt="a dog", wait=False)
        assert "img-nowait" in result
        assert not result.startswith("{")
```

Run: `uv run pytest tests/test_tools_generation.py::TestGenerateImageWait -v`
Expected: FAIL — `generate_image` doesn't accept `wait`

- [ ] **Step 2: Add wait param to generate_image**

In `src/comfyui_mcp/tools/generation.py`, update `generate_image`:

```python
    @mcp.tool()
    async def generate_image(
        prompt: str,
        negative_prompt: str = "bad quality, blurry",
        width: int = 512,
        height: int = 512,
        steps: int = 20,
        cfg: float = 7.0,
        model: str = "",
        wait: bool = False,
    ) -> str:
        """Generate an image from a text prompt using a default txt2img workflow.

        Args:
            prompt: Text description of the image to generate
            negative_prompt: What to avoid in the image
            width: Image width in pixels (64-4096)
            height: Image height in pixels (64-4096)
            steps: Number of sampling steps (more = better quality, slower)
            cfg: Classifier-free guidance scale (higher = more prompt adherence)
            model: Checkpoint model name (leave empty for default)
            wait: If True, block until generation completes and return structured result.
                  If False (default), return immediately with just the prompt_id.
        """
        # ... existing validation unchanged ...

        limiter.check("generate_image")
        wf = _build_txt2img_workflow(prompt, negative_prompt, width, height, steps, cfg, model)

        inspection = inspector.inspect(wf)
        audit.log(
            tool="generate_image",
            action="inspected",
            nodes_used=inspection.nodes_used,
            warnings=inspection.warnings,
            extra={"prompt": prompt, "width": width, "height": height},
        )

        warning_msg = _format_warnings(inspection.warnings)

        response = await client.post_prompt(wf)
        prompt_id = response.get("prompt_id", "unknown")
        audit.log(tool="generate_image", action="submitted", prompt_id=prompt_id)

        if wait and progress is not None:
            state = await progress.wait_for_completion(prompt_id)
            audit.log(
                tool="generate_image",
                action="completed",
                prompt_id=prompt_id,
                extra={"status": state.status, "elapsed": state.elapsed_seconds},
            )
            result_dict = state.to_dict()
            if inspection.warnings:
                result_dict["warnings"] = inspection.warnings
            return json.dumps(result_dict)

        return f"Image generation started. prompt_id: {prompt_id}{warning_msg}"
```

**Important:** In the existing `generate_image` function, rename `result = inspector.inspect(wf)` to `inspection = inspector.inspect(wf)`, and update all references: `result.nodes_used` → `inspection.nodes_used`, `result.warnings` → `inspection.warnings` (4 occurrences total). The code above shows the final state after this rename.

- [ ] **Step 3: Verify all tests pass**

Run: `uv run pytest tests/test_tools_generation.py -v`
Expected: PASS

- [ ] **Step 4: Run linters**

Run: `uv run ruff check src/comfyui_mcp/tools/generation.py && uv run mypy src/comfyui_mcp/tools/generation.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py
git commit -m "feat: add wait parameter to generate_image for blocking execution"
```

---

### Task 6: Wire WebSocketProgress in server.py

**Files:**
- Modify: `src/comfyui_mcp/server.py:9-89`

**Context:** Create `WebSocketProgress` in `_build_server()` and pass it to `register_generation_tools` and `register_job_tools`. `register_generation_tools` already uses `read_limiter=` kwarg. `register_job_tools` now accepts `read_limiter=` and `progress=` kwargs.

- [ ] **Step 1: Update server.py imports and wiring**

Add import at top of `server.py`:
```python
from comfyui_mcp.progress import WebSocketProgress
```

In `_register_all_tools`, add `progress` parameter and update calls:

```python
def _register_all_tools(
    server: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    rate_limiters: dict[str, RateLimiter],
    inspector: WorkflowInspector,
    sanitizer: PathSanitizer,
    node_auditor: NodeAuditor,
    progress: WebSocketProgress,
) -> None:
    """Register all MCP tool groups with their dependencies."""
    register_discovery_tools(server, client, audit, rate_limiters["read"], sanitizer, node_auditor)
    register_history_tools(server, client, audit, rate_limiters["read"])
    register_job_tools(
        server, client, audit, rate_limiters["workflow"],
        read_limiter=rate_limiters["read"], progress=progress,
    )
    register_file_tools(server, client, audit, rate_limiters["file"], sanitizer)
    register_generation_tools(
        server, client, audit, rate_limiters["generation"], inspector,
        read_limiter=rate_limiters["read"], progress=progress,
    )
    register_workflow_tools(server, client, audit, rate_limiters["read"], inspector)
```

In `_build_server`, create `progress` before calling `_register_all_tools`:

```python
    progress = WebSocketProgress(client, timeout=settings.comfyui.timeout_read)
    _register_all_tools(server, client, audit, rate_limiters, inspector, sanitizer, node_auditor, progress)
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS (all tests)

- [ ] **Step 3: Run all linters**

Run: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/comfyui_mcp/`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/comfyui_mcp/server.py
git commit -m "feat: wire WebSocketProgress into server tool registration"
```

---

### Task 7: Final verification and cleanup

- [ ] **Step 1: Run full test suite with coverage**

Run: `uv run pytest --cov=src/comfyui_mcp --cov-report=term-missing -v`
Expected: PASS, verify `progress.py` has good coverage

- [ ] **Step 2: Run pre-commit hooks**

Run: `uv run pre-commit run --all-files`
Expected: PASS

- [ ] **Step 3: Verify no rule violations**

Check against CLAUDE.md rules:
- Rule 3: `get_progress` calls `limiter.check()` ✓
- Rule 4: `get_progress` calls `audit.log()` ✓
- Rule 6: `websockets` is imported in `progress.py` ✓
- Rule 7: `get_progress` is a new tool with unique purpose ✓
- Rule 11: `register_job_tools` and `register_generation_tools` return `dict[str, Any]` ✓
- Rule 16: Tests mock HTTP with `respx`, WebSocket with fakes ✓
