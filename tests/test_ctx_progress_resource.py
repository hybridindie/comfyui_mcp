"""Tests for ctx.report_progress + ctx.read_resource in generation tools (#140).

Verifies the generation tools use the FastMCP 4 Context object to:
- report progress as MCP notifications during streaming workflow execution
- validate a named model exists via the comfyui://models resource before
  building the workflow (reuse the resource layer instead of calling
  client.get_models directly)

Direct/test callers (ctx=None) keep the pre-existing behavior.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.progress import ProgressState, WebSocketProgress
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.generation import _build_txt2img_workflow, _submit_workflow


@pytest.fixture
def deps(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    progress = WebSocketProgress(client)
    inspector = WorkflowInspector(mode="audit", dangerous_nodes=[], allowed_nodes=[])
    sanitizer = PathSanitizer(allowed_extensions=[".png", ".safetensors"])
    return client, audit, progress, inspector, sanitizer


class TestReportProgressOnStream:
    @respx.mock
    async def test_stream_reports_progress_when_ctx_available(self, deps):
        """run_workflow_stream calls ctx.report_progress(step, total) as
        progress events arrive — clients get live MCP notifications instead
        of polling. The final result envelope is unchanged."""
        client, audit, progress, inspector, _sanitizer = deps
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "p-1"})
        )
        # Stub wait_for_completion_with_events to return a final state with
        # step/total_steps and a progress event, so _submit_workflow has the
        # values to report.
        final_state = ProgressState(prompt_id="p-1", status="completed", step=10, total_steps=20)
        events = [{"type": "progress", "data": {"value": 10, "max": 20}}]
        progress.wait_for_completion_with_events = AsyncMock(return_value=(final_state, events))

        ctx = AsyncMock()
        result = await _submit_workflow(
            wf=_build_txt2img_workflow("test"),
            tool_name="run_workflow_stream",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=progress,
            stream_events=True,
            ctx=ctx,
        )
        assert result["status"] == "completed"
        # ctx.report_progress must have been called with the step/total
        ctx.report_progress.assert_awaited()
        # At least one call reported the step/total from the progress event
        calls = ctx.report_progress.call_args_list
        assert any(call.args[0] == 10 and call.args[1] == 20 for call in calls), (
            f"report_progress not called with (10, 20): {calls}"
        )

    @respx.mock
    async def test_stream_no_ctx_keeps_existing_behavior(self, deps):
        """Direct callers with ctx=None still get the stream result without
        requiring a Context — no report_progress call attempted."""
        client, audit, progress, inspector, _sanitizer = deps
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "p-1"})
        )
        final_state = ProgressState(prompt_id="p-1", status="completed", step=5, total_steps=5)
        events = [{"type": "progress", "data": {"value": 5, "max": 5}}]
        progress.wait_for_completion_with_events = AsyncMock(return_value=(final_state, events))

        result = await _submit_workflow(
            wf=_build_txt2img_workflow("test"),
            tool_name="run_workflow_stream",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=progress,
            stream_events=True,
        )
        assert result["status"] == "completed"


class TestReadResourceModelValidation:
    async def test_generate_image_validates_model_via_resource(self, deps):
        """When ctx is available and a model is specified, generate_image
        reads the comfyui://models/checkpoints resource to confirm the model
        exists before building the workflow. A nonexistent model fails fast
        without hitting /prompt."""
        _client, _audit, _progress, _inspector, _sanitizer = deps
        ctx = AsyncMock()
        # Simulate the resource read returning a list that does NOT contain
        # the requested model — the tool should fail fast.
        ctx.read_resource = AsyncMock(
            return_value=MagicMock(
                contents=[MagicMock(content=json.dumps({"models": ["other.safetensors"]}))]
            )
        )
        # Build the txt2img workflow directly via the helper to assert the
        # model-validation gate rejects before submission. This tests the
        # _validate_model_via_resource helper added in #140.
        from comfyui_mcp.tools.generation import _validate_model_via_resource

        with pytest.raises(ValueError, match="not found"):
            await _validate_model_via_resource(
                folder="checkpoints",
                model="nonexistent.safetensors",
                ctx=ctx,
            )
        # The resource was read (one round-trip), and /prompt was NOT hit
        ctx.read_resource.assert_awaited_once()

    async def test_validate_model_no_ctx_skips_resource_read(self, deps):
        """Without ctx (direct/test callers), model validation skips the
        resource read and returns None — keep the pre-existing behavior."""
        from comfyui_mcp.tools.generation import _validate_model_via_resource

        result = await _validate_model_via_resource(
            folder="checkpoints", model="anything.safetensors", ctx=None
        )
        assert result is None

    async def test_validate_model_present_does_not_raise(self, deps):
        """When the model IS in the resource listing, validation passes."""
        ctx = AsyncMock()
        ctx.read_resource = AsyncMock(
            return_value=MagicMock(
                contents=[MagicMock(content=json.dumps({"models": ["flux-dev.safetensors"]}))]
            )
        )
        from comfyui_mcp.tools.generation import _validate_model_via_resource

        result = await _validate_model_via_resource(
            folder="checkpoints", model="flux-dev.safetensors", ctx=ctx
        )
        assert result is None  # no raise
