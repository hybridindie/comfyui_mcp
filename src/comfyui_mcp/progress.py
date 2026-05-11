"""WebSocket progress tracking for ComfyUI workflow execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx
import websockets

from comfyui_mcp.client import ComfyUIClient

_logger = logging.getLogger(__name__)


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


class WebSocketProgress:
    """Manages on-demand WebSocket connections for progress tracking."""

    @staticmethod
    def _extract_outputs(node_id: str, node_output: dict[str, Any]) -> list[dict[str, str]]:
        """Extract output file info from a node's output data."""
        items: list[dict[str, str]] = []
        for key in ("images", "gifs"):
            for item in node_output.get(key, []):
                items.append(
                    {
                        "node_id": node_id,
                        "filename": item.get("filename", ""),
                        "subfolder": item.get("subfolder", ""),
                    }
                )
        return items

    def __init__(
        self, client: ComfyUIClient, timeout: float = 300.0, tls_verify: bool = True
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._tls_verify = tls_verify
        self._client_id = uuid.uuid4().hex

    def new_client_id(self) -> str:
        """Create a fresh websocket client_id for per-prompt event isolation."""
        return uuid.uuid4().hex

    @property
    def client_id(self) -> str:
        """Return the client_id used for WebSocket connections."""
        return self._client_id

    def _ws_url(self, client_id: str) -> str:
        """Derive WebSocket URL from client's HTTP base URL."""
        parsed = urlparse(self._client.base_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        return f"{ws_scheme}://{parsed.netloc}/ws?clientId={client_id}"

    def _update_state_from_event(
        self,
        state: ProgressState,
        msg_type: str,
        data: dict[str, Any],
    ) -> bool:
        """Apply a ComfyUI websocket event to state and return True when terminal."""
        if msg_type == "progress":
            state.step = data.get("value")
            state.total_steps = data.get("max")
            return False

        if msg_type == "executing":
            node = data.get("node")
            if node is None:
                # null node means execution finished
                state.status = "completed"
                return True
            state.current_node = node
            return False

        if msg_type == "executed":
            output = data.get("output", {})
            state.outputs.extend(self._extract_outputs(data.get("node", ""), output))
            return False

        if msg_type == "execution_success":
            state.status = "completed"
            return True

        if msg_type == "execution_interrupted":
            state.status = "interrupted"
            return True

        if msg_type == "execution_error":
            state.status = "error"
            return True

        return False

    # Map ComfyUI's /api/jobs status enum to our internal ProgressState.status names.
    # Upstream uses "in_progress" / "pending" / "completed" / "failed" / "cancelled".
    _STATUS_MAP: ClassVar[dict[str, str]] = {
        "completed": "completed",
        "failed": "error",
        "cancelled": "interrupted",
        "in_progress": "running",
        "pending": "queued",
    }

    def _state_from_job(self, job: dict[str, Any], prompt_id: str) -> ProgressState:
        """Build a ProgressState from a /api/jobs/{id} response."""
        upstream_status = job.get("status", "")
        state = ProgressState(
            prompt_id=prompt_id,
            status=self._STATUS_MAP.get(upstream_status, "unknown"),
        )
        outputs = job.get("outputs") or {}
        if isinstance(outputs, dict):
            for node_id, node_output in outputs.items():
                if isinstance(node_output, dict):
                    state.outputs.extend(self._extract_outputs(node_id, node_output))
        return state

    async def _wait_internal(
        self,
        prompt_id: str,
        *,
        client_id: str,
        collect_events: bool,
    ) -> tuple[ProgressState, list[dict[str, Any]]]:
        """Connect via WebSocket and wait until completion with optional event capture."""
        state = ProgressState(prompt_id=prompt_id, status="running")
        events: list[dict[str, Any]] = []
        start_time = time.monotonic()

        try:
            ws_kwargs: dict[str, Any] = {}
            ws_url = self._ws_url(client_id)
            if ws_url.startswith("wss://") and not self._tls_verify:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ws_kwargs["ssl"] = ctx

            async with asyncio.timeout(self._timeout):
                async with websockets.connect(ws_url, **ws_kwargs) as ws:
                    # Pre-flight: if the job finished before this WS connection was
                    # established, ComfyUI will not replay terminal events. Hit the
                    # unified /api/jobs/{id} endpoint immediately to avoid hanging
                    # until timeout.
                    with contextlib.suppress(httpx.HTTPError, OSError):
                        job = await self._client.get_job(prompt_id)
                        if job and job.get("status") in {"completed", "failed", "cancelled"}:
                            state = self._state_from_job(job, prompt_id)
                            if collect_events:
                                events.append(
                                    {
                                        "type": "preflight_terminal",
                                        "data": {"prompt_id": prompt_id},
                                    }
                                )
                            state.elapsed_seconds = round(time.monotonic() - start_time, 2)
                            return state, events

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

                        if collect_events:
                            events.append({"type": msg_type, "data": data})

                        if self._update_state_from_event(state, msg_type, data):
                            break

        except TimeoutError:
            state.status = "timeout"
        except (OSError, websockets.exceptions.WebSocketException) as exc:
            # WebSocket failed — fall back to HTTP polling per spec
            _logger.warning("WebSocket connection failed, falling back to HTTP polling: %s", exc)
            state = await self._poll_until_complete(prompt_id, start_time)
            if collect_events:
                events.append({"type": "fallback_polling", "data": {"prompt_id": prompt_id}})

        state.elapsed_seconds = round(time.monotonic() - start_time, 2)
        return state, events

    async def wait_for_completion(
        self,
        prompt_id: str,
        *,
        client_id: str | None = None,
    ) -> ProgressState:
        """Connect via WebSocket and block until the prompt completes, errors, or times out."""
        ws_client_id = client_id or self._client_id
        state, _events = await self._wait_internal(
            prompt_id,
            client_id=ws_client_id,
            collect_events=False,
        )
        return state

    async def wait_for_completion_with_events(
        self,
        prompt_id: str,
        *,
        client_id: str | None = None,
    ) -> tuple[ProgressState, list[dict[str, Any]]]:
        """Connect via WebSocket and return completion state plus captured stream events."""
        ws_client_id = client_id or self._client_id
        return await self._wait_internal(
            prompt_id,
            client_id=ws_client_id,
            collect_events=True,
        )

    # ProgressState.status values that end the HTTP-polling fallback loop.
    # Must mirror every terminal status _STATUS_MAP can produce — otherwise a
    # job in a terminal state would keep polling until timeout.
    _TERMINAL_STATUSES: ClassVar[frozenset[str]] = frozenset({"completed", "error", "interrupted"})

    async def _poll_until_complete(self, prompt_id: str, start_time: float) -> ProgressState:
        """Poll HTTP endpoints until completion or timeout."""
        interval = 1.0
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= self._timeout:
                state = ProgressState(prompt_id=prompt_id, status="timeout")
                state.elapsed_seconds = round(elapsed, 2)
                return state
            state = await self.get_state(prompt_id)
            if state.status in self._TERMINAL_STATUSES:
                state.elapsed_seconds = round(time.monotonic() - start_time, 2)
                return state
            await asyncio.sleep(interval)
            interval = min(interval * 1.5, 10.0)

    async def get_state(self, prompt_id: str) -> ProgressState:
        """Get current state via the unified /api/jobs/{id} endpoint.

        For pending jobs we additionally consult /queue (best-effort) to derive
        ``queue_position`` — the unified job response does not expose it.
        """
        job: dict[str, Any] | None = None
        with contextlib.suppress(httpx.HTTPError, OSError):
            job = await self._client.get_job(prompt_id)

        if job is None:
            return ProgressState(prompt_id=prompt_id)

        state = self._state_from_job(job, prompt_id)

        if state.status == "queued":
            with contextlib.suppress(httpx.HTTPError, OSError):
                queue = await self._client.get_queue()
                pending = queue.get("queue_pending", [])
                for i, item in enumerate(pending):
                    if len(item) >= 2 and item[1] == prompt_id:
                        state.queue_position = i + 1
                        break

        return state
