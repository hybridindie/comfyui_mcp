"""Workflow composition tools: create, modify, validate, analyze."""

from __future__ import annotations

import contextlib
import json
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer, PathValidationError
from comfyui_mcp.workflow.operations import apply_operations
from comfyui_mcp.workflow.templates import create_from_template
from comfyui_mcp.workflow.validation import analyze_workflow as _analyze_workflow
from comfyui_mcp.workflow.validation import validate_workflow as _validate_workflow

_MAX_WORKFLOW_JSON_BYTES = 10 * 1024 * 1024  # 10 MB

_PATH_LIKE_TEMPLATE_PARAMS = {
    "model",
    "model_name",
    "motion_module",
    "controlnet_model",
    "ipadapter_model",
    "clip_vision_model",
    "lora_name",
    "face_restore_model",
    "image",
    "mask",
}


def _sanitize_template_params(
    param_dict: dict[str, Any], sanitizer: PathSanitizer
) -> dict[str, Any]:
    """Sanitize filename-like template params to block traversal/null-byte inputs."""
    sanitized = dict(param_dict)
    for key in _PATH_LIKE_TEMPLATE_PARAMS:
        value = sanitized.get(key)
        if isinstance(value, str):
            sanitized[key] = sanitizer.validate_path_segment(value, label=key)
    return sanitized


def register_workflow_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    inspector: WorkflowInspector,
    sanitizer: PathSanitizer,
) -> dict[str, Any]:
    """Register workflow composition tools."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def comfyui_create_workflow(template: str, params: str = "") -> dict[str, Any]:
        """Create a ComfyUI workflow from a template with optional parameter overrides.

        Available templates: ``txt2img``, ``img2img``, ``upscale``, ``inpaint``,
        ``txt2vid_animatediff``, ``txt2vid_wan``, ``controlnet_canny``,
        ``controlnet_depth``, ``controlnet_openpose``, ``ip_adapter``,
        ``lora_stack``, ``face_restore``, ``flux_txt2img``, ``sdxl_txt2img``.

        Args:
            template (required): Template name from the list above.
            params (optional): JSON string of parameter overrides. Defaults to
                an empty string, meaning "use template defaults". Pass either
                ``""`` or ``"{}"`` for no overrides. Common keys:
                ``prompt``, ``negative_prompt``, ``width``, ``height``,
                ``steps``, ``cfg``, ``model``, ``denoise``, ``controlnet_model``,
                ``control_strength``, ``lora_name``, ``lora_strength``.

        Example:
            ``comfyui_create_workflow(template="txt2img",
            params='{"prompt": "a sunset", "width": 768, "steps": 30}')``
        """
        limiter.check("create_workflow")
        if len(params.encode("utf-8")) > _MAX_WORKFLOW_JSON_BYTES:
            raise ValueError(
                f"Workflow JSON exceeds maximum size ({_MAX_WORKFLOW_JSON_BYTES} bytes)"
            )

        # Empty string is the natural "no overrides" form. Treat it as {} so
        # callers don't have to pass the literal '{}'.
        if not params.strip():
            param_dict: dict[str, Any] = {}
        else:
            try:
                param_dict = json.loads(params)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON params: {e}") from e

            if not isinstance(param_dict, dict):
                raise ValueError('params must be a JSON object (e.g. {"key": "value"})')

        try:
            clean_params = _sanitize_template_params(param_dict, sanitizer)
        except PathValidationError as e:
            raise ValueError(str(e)) from e

        wf = create_from_template(template, clean_params)
        await audit.async_log(
            tool="create_workflow",
            action="created",
            extra={"template": template, "node_count": len(wf)},
        )
        return wf

    tool_fns["comfyui_create_workflow"] = comfyui_create_workflow

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def comfyui_modify_workflow(workflow: str, operations: str) -> dict[str, Any]:
        """Apply batch operations to a ComfyUI workflow.

        Operations execute sequentially in array order. If any operation fails,
        the workflow is returned unchanged (transactional).

        Args:
            workflow (required): JSON string of the workflow to modify.
            operations (required): JSON string of an array of operation objects.

        Operation reference:

        - ``add_node`` — append a new node. Fields:
          ``{"op": "add_node", "class_type": "<NodeType>",
             "node_id": "<id>" (optional, auto-assigned if omitted),
             "inputs": {...} (optional default inputs)}``
        - ``remove_node`` — drop a node. Fields:
          ``{"op": "remove_node", "node_id": "<id>"}``
        - ``set_input`` — set or replace a single input value. Fields:
          ``{"op": "set_input", "node_id": "<id>",
             "input_name": "<key>", "value": <any>}``
        - ``connect`` — wire one node's output into another's input. Fields:
          ``{"op": "connect", "from_node": "<id>", "from_output": <int>,
             "to_node": "<id>", "to_input": "<key>"}``
        - ``disconnect`` — clear an existing input connection. Fields:
          ``{"op": "disconnect", "node_id": "<id>", "input_name": "<key>"}``

        Example:
            ``operations='[{"op": "set_input", "node_id": "3",
            "input_name": "steps", "value": 50},
            {"op": "add_node", "class_type": "LoraLoader"}]'``
        """
        limiter.check("modify_workflow")
        if len(workflow.encode("utf-8")) > _MAX_WORKFLOW_JSON_BYTES:
            raise ValueError(
                f"Workflow JSON exceeds maximum size ({_MAX_WORKFLOW_JSON_BYTES} bytes)"
            )
        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e

        if not isinstance(wf, dict):
            raise ValueError("Workflow must be a JSON object keyed by node IDs")

        if len(operations.encode("utf-8")) > _MAX_WORKFLOW_JSON_BYTES:
            raise ValueError(
                f"Workflow JSON exceeds maximum size ({_MAX_WORKFLOW_JSON_BYTES} bytes)"
            )
        try:
            ops = json.loads(operations)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON operations: {e}") from e

        if not isinstance(ops, list) or not all(isinstance(op, dict) for op in ops):
            raise ValueError("Operations must be a JSON array of operation objects")

        result = apply_operations(wf, ops)
        await audit.async_log(
            tool="modify_workflow",
            action="modified",
            extra={"operations": len(ops), "node_count": len(result)},
        )
        return result

    tool_fns["comfyui_modify_workflow"] = comfyui_modify_workflow

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_analyze_workflow(workflow: str) -> dict[str, Any]:
        """Analyze a ComfyUI workflow and return its structured shape.

        Unlike ``comfyui_summarize_workflow`` (which formats a human-readable
        text or Mermaid summary), this tool returns the raw analysis as a dict
        so callers can read individual fields directly without parsing prose.

        Args:
            workflow (required): JSON string of the workflow to analyze. The
                workflow JSON is a dict keyed by node ID; each value has
                ``class_type`` and ``inputs``.

        Returns:
            Dict with keys:

            - ``node_count`` (int): number of nodes in the workflow.
            - ``class_types`` (list[str]): every ``class_type`` in topological
              order.
            - ``flow`` (list[dict]): per-node info — ``node_id``, ``class_type``,
              ``display_name``, ``inputs`` — in topological order.
            - ``models`` (list[dict]): single-field loader values, e.g.
              ``[{"name": "v1-5-pruned.safetensors", "type": "checkpoints"}]``.
            - ``parameters`` (dict): flat key/value of common sampler/latent
              parameters extracted from the graph (``steps``, ``cfg``, ``width``,
              ``height``, etc.).
            - ``pipeline`` (str): coarse type — ``txt2img``, ``img2img``,
              ``upscale``, ``img2img -> upscale``, or ``unknown``.
            - ``prompt_nodes`` (list[str]): ids of ``CLIPTextEncode`` nodes
              wired into the sampler's positive input.
            - ``negative_nodes`` (list[str]): ids of ``CLIPTextEncode`` nodes
              wired into the sampler's negative input.

        Display-name enrichment is best-effort via ComfyUI's ``/object_info``
        endpoint; if the server is unreachable, ``display_name`` falls back to
        the bare ``class_type``.
        """
        limiter.check("analyze_workflow")
        if len(workflow.encode("utf-8")) > _MAX_WORKFLOW_JSON_BYTES:
            raise ValueError(
                f"Workflow JSON exceeds maximum size ({_MAX_WORKFLOW_JSON_BYTES} bytes)"
            )
        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e

        if not isinstance(wf, dict):
            raise ValueError("Workflow must be a JSON object keyed by node IDs")

        # Best-effort enrichment from /object_info — analyzer handles None.
        object_info: dict[str, Any] | None = None
        with contextlib.suppress(httpx.HTTPError, OSError):
            object_info = await client.get_object_info()

        result = dict(_analyze_workflow(wf, object_info))
        await audit.async_log(
            tool="analyze_workflow",
            action="analyzed",
            extra={"node_count": result["node_count"], "pipeline": result["pipeline"]},
        )
        return result

    tool_fns["comfyui_analyze_workflow"] = comfyui_analyze_workflow

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_validate_workflow(workflow: str) -> dict[str, Any]:
        """Validate a ComfyUI workflow for structural correctness and security.

        Checks: node structure, connection references, installed node types,
        available models, dangerous nodes, and suspicious inputs.

        Args:
            workflow (required): JSON string of the workflow to validate.

        Returns:
            Dict with keys:

            - ``valid`` (bool): True only if there are zero entries in ``errors``.
            - ``errors`` (list[str]): blocking issues — invalid structure,
              connections that reference nonexistent nodes, missing required
              inputs, etc. Each entry is a human-readable string identifying
              the offending node id and what's wrong.
            - ``warnings`` (list[str]): non-blocking concerns — unknown
              ``class_type`` not advertised by the connected server,
              missing model files, dangerous node names, suspicious input
              patterns (e.g. ``__import__``).
            - ``node_count`` (int): number of nodes in the workflow.
            - ``pipeline`` (str): coarse type — ``txt2img``, ``img2img``,
              ``upscale``, ``img2img -> upscale``, or ``unknown``. (For the
              full structural breakdown, use ``comfyui_analyze_workflow``.)
        """
        limiter.check("validate_workflow")
        if len(workflow.encode("utf-8")) > _MAX_WORKFLOW_JSON_BYTES:
            raise ValueError(
                f"Workflow JSON exceeds maximum size ({_MAX_WORKFLOW_JSON_BYTES} bytes)"
            )
        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e

        if not isinstance(wf, dict):
            raise ValueError("Workflow must be a JSON object keyed by node IDs")

        result = await _validate_workflow(wf, client, inspector)
        await audit.async_log(
            tool="validate_workflow",
            action="validated",
            extra={
                "valid": result["valid"],
                "error_count": len(result["errors"]),
                "warning_count": len(result["warnings"]),
            },
        )
        return result

    tool_fns["comfyui_validate_workflow"] = comfyui_validate_workflow

    return tool_fns
