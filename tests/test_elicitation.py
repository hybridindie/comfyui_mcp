"""Tests for elicitation-gated workflow submission (Phase 5).

Verifies that enforce-mode workflows with dangerous-node warnings gate
through ctx.elicit() — the tool blocks until the user confirms, rather
than raising WorkflowBlockedError immediately. Audit-mode workflows and
direct (no-ctx) callers keep the existing behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.progress import WebSocketProgress
from comfyui_mcp.security.inspector import WorkflowBlockedError, WorkflowInspector
from comfyui_mcp.tools.generation import _submit_workflow


def _wf_with_dangerous_node() -> dict:
    """A workflow with a suspicious-input warning but no unapproved nodes.

    Uses CLIPTextEncode (an allowed node) with an eval() call in the prompt
    text — this triggers a suspicious-input warning without the unapproved-node
    raise that would preempt the elicitation gate. The elicitation fires on
    inspection.warnings, which suspicious-input warnings populate.
    """
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "model.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "eval('malicious')", "clip": ["1", 1]},
        },
        "3": {
            "class_type": "SaveImage",
            "inputs": {"images": ["1", 0]},
        },
    }


@pytest.fixture
def enforce_inspector() -> WorkflowInspector:
    return WorkflowInspector(
        mode="enforce",
        dangerous_nodes=["ExecTextNode"],
        allowed_nodes=["CheckpointLoaderSimple", "CLIPTextEncode", "SaveImage"],
    )


@pytest.fixture
def audit_inspector() -> WorkflowInspector:
    return WorkflowInspector(
        mode="audit",
        dangerous_nodes=["ExecTextNode"],
        allowed_nodes=["CheckpointLoaderSimple", "CLIPTextEncode", "SaveImage"],
    )


@pytest.fixture
def deps(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    progress = WebSocketProgress(client)
    return client, audit, progress


class TestEnforceModeElicitationGate:
    @respx.mock
    async def test_accept_proceeds_with_submission(self, deps, enforce_inspector):
        """When the user accepts (data=True), the workflow is submitted
        despite the enforce-mode warning — the elicitation is the gate."""
        client, audit, progress = deps
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )
        ctx = AsyncMock()
        from fastmcp.server.elicitation import AcceptedElicitation

        ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data=True))

        result = await _submit_workflow(
            wf=_wf_with_dangerous_node(),
            tool_name="run_workflow",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=enforce_inspector,
            progress=progress,
            ctx=ctx,
        )
        assert result["status"] == "submitted"
        assert result["prompt_id"] == "abc-123"
        ctx.elicit.assert_awaited_once()

    @respx.mock
    async def test_decline_raises_workflow_blocked(self, deps, enforce_inspector):
        """When the user declines, the workflow is NOT submitted —
        WorkflowBlockedError propagates without calling post_prompt."""
        client, audit, progress = deps
        post_route = respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc"})
        )
        ctx = AsyncMock()
        from fastmcp.server.elicitation import DeclinedElicitation

        ctx.elicit = AsyncMock(return_value=DeclinedElicitation())

        with pytest.raises(WorkflowBlockedError):
            await _submit_workflow(
                wf=_wf_with_dangerous_node(),
                tool_name="run_workflow",
                success_message="ok",
                wait=False,
                client=client,
                audit=audit,
                inspector=enforce_inspector,
                progress=progress,
                ctx=ctx,
            )
        # The POST must not have been called — we blocked before submission.
        assert post_route.calls.call_count == 0
        ctx.elicit.assert_awaited_once()

    @respx.mock
    async def test_cancel_raises_workflow_blocked(self, deps, enforce_inspector):
        """When the user cancels, the workflow is NOT submitted."""
        client, audit, progress = deps
        post_route = respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc"})
        )
        ctx = AsyncMock()
        from fastmcp.server.elicitation import CancelledElicitation

        ctx.elicit = AsyncMock(return_value=CancelledElicitation())

        with pytest.raises(WorkflowBlockedError):
            await _submit_workflow(
                wf=_wf_with_dangerous_node(),
                tool_name="run_workflow",
                success_message="ok",
                wait=False,
                client=client,
                audit=audit,
                inspector=enforce_inspector,
                progress=progress,
                ctx=ctx,
            )
        assert post_route.calls.call_count == 0

    @respx.mock
    async def test_accept_false_raises_workflow_blocked(self, deps, enforce_inspector):
        """When the user accepts but answers False (do not proceed), block."""
        client, audit, progress = deps
        post_route = respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc"})
        )
        ctx = AsyncMock()
        from fastmcp.server.elicitation import AcceptedElicitation

        ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data=False))

        with pytest.raises(WorkflowBlockedError):
            await _submit_workflow(
                wf=_wf_with_dangerous_node(),
                tool_name="run_workflow",
                success_message="ok",
                wait=False,
                client=client,
                audit=audit,
                inspector=enforce_inspector,
                progress=progress,
                ctx=ctx,
            )
        assert post_route.calls.call_count == 0


class TestNoCtxFallback:
    @respx.mock
    async def test_no_ctx_keeps_raise_behavior(self, deps, enforce_inspector):
        """Direct callers with no ctx (tests, programmatic) keep the existing
        behavior: WorkflowBlockedError is raised immediately in enforce mode
        with warnings. The elicitation gate only fires when ctx is provided."""
        client, audit, progress = deps
        post_route = respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc"})
        )
        with pytest.raises(WorkflowBlockedError):
            await _submit_workflow(
                wf=_wf_with_dangerous_node(),
                tool_name="run_workflow",
                success_message="ok",
                wait=False,
                client=client,
                audit=audit,
                inspector=enforce_inspector,
                progress=progress,
            )
        assert post_route.calls.call_count == 0


class TestAuditModeBypassesElicitation:
    @respx.mock
    async def test_audit_mode_no_elicitation_even_with_warnings(self, deps, audit_inspector):
        """Audit mode never blocks and never elicits — warnings are logged
        and the workflow is submitted."""
        client, audit, progress = deps
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )
        ctx = AsyncMock()

        result = await _submit_workflow(
            wf=_wf_with_dangerous_node(),
            tool_name="run_workflow",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=audit_inspector,
            progress=progress,
            ctx=ctx,
        )
        assert result["status"] == "submitted"
        ctx.elicit.assert_not_awaited()


class TestNoWarningsNoElicitation:
    @respx.mock
    async def test_clean_workflow_no_elicitation_in_enforce_mode(self, deps, enforce_inspector):
        """A workflow with no warnings in enforce mode is submitted without
        elicitation — the gate only fires when warnings are present."""
        client, audit, progress = deps
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )
        ctx = AsyncMock()

        clean_wf = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"},
            },
            "2": {
                "class_type": "SaveImage",
                "inputs": {"images": ["1", 0]},
            },
        }

        result = await _submit_workflow(
            wf=clean_wf,
            tool_name="run_workflow",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=enforce_inspector,
            progress=progress,
            ctx=ctx,
        )
        assert result["status"] == "submitted"
        ctx.elicit.assert_not_awaited()
