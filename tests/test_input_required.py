"""Sessionless (2026-07-28) consent via the InputRequiredResult guard (#210).

Handshake connections keep using ``ctx.elicit``. Sessionless connections get an
``InputRequiredResult`` on the first round and the client retries with
``ctx.input_responses``; the gate reads the answer there and fails closed.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.types import ElicitResult, InputRequiredResult

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.node_manager import ComfyUIManagerDetector
from comfyui_mcp.security.consent import (
    ConsentDeniedError,
    read_approval,
    request_approval,
    require_confirmation,
    uses_input_required,
)
from comfyui_mcp.security.inspector import WorkflowBlockedError, WorkflowInspector
from comfyui_mcp.security.node_auditor import NodeAuditor
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.generation import _submit_workflow
from comfyui_mcp.tools.nodes import register_node_tools
from comfyui_mcp.tools.settings import register_settings_tools


class FakeCtx:
    def __init__(self, protocol_version: str, responses=None):
        self.request_context = SimpleNamespace(protocol_version=protocol_version)
        self.input_responses = responses
        self.elicit = AsyncMock(return_value=AcceptedElicitation(data=True))


def _approve() -> dict[str, ElicitResult]:
    return {"approve": ElicitResult(action="accept", content={"approve": True})}


def _decline() -> dict[str, ElicitResult]:
    return {"approve": ElicitResult(action="decline", content=None)}


@pytest.fixture
def audit(tmp_path):
    return AuditLogger(audit_file=tmp_path / "audit.log")


class TestEraDetection:
    def test_modern_connection_uses_guard(self):
        assert uses_input_required(FakeCtx("2026-07-28")) is True

    def test_handshake_connection_uses_elicit(self):
        assert uses_input_required(FakeCtx("2025-06-18")) is False
        assert uses_input_required(None) is False


class TestGuardShape:
    def test_request_is_a_boolean_approval(self):
        result = request_approval("Approve install?")

        assert isinstance(result, InputRequiredResult)
        assert result.input_requests is not None
        request = result.input_requests["approve"]
        assert request.method == "elicitation/create"
        assert request.params.message == "Approve install?"
        assert request.params.requested_schema["required"] == ["approve"]

    @pytest.mark.parametrize(
        ("responses", "expected"),
        [
            (_approve(), True),
            (_decline(), False),
            ({"approve": ElicitResult(action="cancel", content=None)}, False),
            ({"approve": ElicitResult(action="accept", content={"approve": False})}, False),
            (None, False),
        ],
    )
    def test_read_approval(self, responses, expected):
        ctx = FakeCtx("2026-07-28", responses=responses)
        assert read_approval(ctx) is expected


class TestRequireConfirmationModern:
    async def test_first_round_returns_guard_and_audits(self, audit, tmp_path):
        guard = await require_confirmation(
            FakeCtx("2026-07-28"),
            mode="enforce",
            audit=audit,
            tool="install_custom_node",
            prompt="Install?",
            extra={"node_id": "pack"},
        )

        assert isinstance(guard, InputRequiredResult)
        record = audit._audit_file.read_text().splitlines()[-1]
        assert '"channel":"input_required"' in record

    async def test_retry_accept_proceeds(self, audit):
        result = await require_confirmation(
            FakeCtx("2026-07-28", responses=_approve()),
            mode="enforce",
            audit=audit,
            tool="install_custom_node",
            prompt="Install?",
        )
        assert result is None

    async def test_retry_decline_raises(self, audit):
        with pytest.raises(ConsentDeniedError):
            await require_confirmation(
                FakeCtx("2026-07-28", responses=_decline()),
                mode="enforce",
                audit=audit,
                tool="install_custom_node",
                prompt="Install?",
            )

    async def test_legacy_connection_still_elicit(self, audit):
        ctx = FakeCtx("2025-06-18")

        result = await require_confirmation(
            ctx,
            mode="enforce",
            audit=audit,
            tool="install_custom_node",
            prompt="Install?",
        )

        assert result is None
        ctx.elicit.assert_awaited_once()


def _node_tools(audit, mode="enforce"):
    client = ComfyUIClient(base_url="http://test:8188")
    client.queue_manager_task = AsyncMock(return_value={})
    client.start_custom_node_queue = AsyncMock(return_value={})
    client.get_custom_node_queue_status = AsyncMock(return_value={"is_processing": False})
    node_manager = ComfyUIManagerDetector(client)
    node_manager.require_available = AsyncMock()
    mcp = FastMCP("modern-guard-test")
    return client, register_node_tools(
        mcp=mcp,
        client=client,
        audit=audit,
        wf_limiter=RateLimiter(max_per_minute=10),
        read_limiter=RateLimiter(max_per_minute=10),
        node_manager=node_manager,
        node_auditor=NodeAuditor(),
        mode=mode,
    )


class TestToolIntegration:
    async def test_node_install_returns_guard_before_mutating(self, audit):
        client, tools = _node_tools(audit)

        result = await tools["comfyui_install_custom_node"](
            node_id="comfyui-impact-pack",
            ctx=FakeCtx("2026-07-28"),
        )

        assert isinstance(result, InputRequiredResult)
        client.queue_manager_task.assert_not_awaited()

    async def test_node_install_retry_runs_operation(self, audit):
        client, tools = _node_tools(audit)

        result = await tools["comfyui_install_custom_node"](
            node_id="comfyui-impact-pack",
            ctx=FakeCtx("2026-07-28", responses=_approve()),
        )

        assert "comfyui-impact-pack" in result
        client.queue_manager_task.assert_awaited_once()

    @respx.mock
    async def test_settings_returns_guard_before_post(self, audit):
        route = respx.post("http://test:8188/settings").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("modern-settings-test")
        tools = register_settings_tools(
            mcp,
            ComfyUIClient(base_url="http://test:8188"),
            audit,
            RateLimiter(max_per_minute=10),
            PathSanitizer(allowed_extensions=[".png"]),
            mode="enforce",
        )

        result = await tools["comfyui_update_settings"](
            settings={"default_sampler": "euler"},
            ctx=FakeCtx("2026-07-28"),
        )

        assert isinstance(result, InputRequiredResult)
        assert not route.called


def _wf_with_warning() -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "m.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "eval('x')", "clip": ["1", 1]}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }


@pytest.fixture
def workflow_deps(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    inspector = WorkflowInspector(
        mode="enforce",
        dangerous_nodes=["ExecTextNode"],
        allowed_nodes=["CheckpointLoaderSimple", "CLIPTextEncode", "SaveImage"],
    )
    return client, audit, inspector


@respx.mock
async def test_workflow_returns_guard_and_does_not_submit(workflow_deps):
    client, audit, inspector = workflow_deps
    prompt_route = respx.post("http://test:8188/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "abc"})
    )

    result = await _submit_workflow(
        wf=_wf_with_warning(),
        tool_name="run_workflow",
        success_message="ok",
        wait=False,
        client=client,
        audit=audit,
        inspector=inspector,
        progress=None,
        ctx=FakeCtx("2026-07-28"),
    )

    assert isinstance(result, InputRequiredResult)
    assert not prompt_route.called


@respx.mock
async def test_workflow_retry_accept_submits(workflow_deps):
    client, audit, inspector = workflow_deps
    prompt_route = respx.post("http://test:8188/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "abc"})
    )

    result = await _submit_workflow(
        wf=_wf_with_warning(),
        tool_name="run_workflow",
        success_message="ok",
        wait=False,
        client=client,
        audit=audit,
        inspector=inspector,
        progress=None,
        ctx=FakeCtx("2026-07-28", responses=_approve()),
    )

    assert result["status"] == "submitted"
    assert prompt_route.called


@respx.mock
async def test_workflow_retry_decline_blocks(workflow_deps):
    client, audit, inspector = workflow_deps
    prompt_route = respx.post("http://test:8188/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "abc"})
    )

    with pytest.raises(WorkflowBlockedError):
        await _submit_workflow(
            wf=_wf_with_warning(),
            tool_name="run_workflow",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=None,
            ctx=FakeCtx("2026-07-28", responses=_decline()),
        )

    assert not prompt_route.called
