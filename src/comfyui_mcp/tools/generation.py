"""Generation tools: image generation, workflow execution, and summarization."""

from __future__ import annotations

import contextlib
import copy
import json
from typing import Annotated, Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.progress import WebSocketProgress
from comfyui_mcp.security.inspector import WorkflowBlockedError, WorkflowInspector
from comfyui_mcp.security.model_checker import ModelChecker
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.workflow.templates import create_from_template as _create_from_template
from comfyui_mcp.workflow.validation import INPUT_NODE_TYPES as _INPUT_NODE_TYPES
from comfyui_mcp.workflow.validation import SAMPLER_NODE_TYPES as _SAMPLER_NODE_TYPES
from comfyui_mcp.workflow.validation import WorkflowAnalysis
from comfyui_mcp.workflow.validation import analyze_workflow as _analyze_workflow

MAX_WIDTH = 4096
MAX_HEIGHT = 4096
MIN_DIMENSION = 64

_MAX_WORKFLOW_JSON_BYTES = 10 * 1024 * 1024  # 10 MB


def _validate_steps(steps: int) -> None:
    if steps < 1 or steps > 100:
        raise ValueError("steps must be between 1 and 100")


def _validate_cfg(cfg: float) -> None:
    if cfg < 1.0 or cfg > 30.0:
        raise ValueError("cfg must be between 1.0 and 30.0")


def _validate_strength(strength: float) -> None:
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must be between 0.0 and 1.0")


# -- Annotated field types for Pydantic schema generation --
# These provide JSON schema constraints (ge, le, etc.) and descriptions
# that MCP clients use for tool parameter documentation and validation.
# Manual validators above are kept for direct-call safety (e.g. tests).

StepsField = Annotated[int, Field(description="Number of sampling steps", ge=1, le=100)]
CfgField = Annotated[
    float,
    Field(description="Classifier-free guidance scale", ge=1.0, le=30.0),
]
StrengthField = Annotated[
    float,
    Field(description="How much to deviate from the input image", ge=0.0, le=1.0),
]
WidthField = Annotated[
    int,
    Field(description="Image width in pixels", ge=MIN_DIMENSION, le=MAX_WIDTH),
]
HeightField = Annotated[
    int,
    Field(description="Image height in pixels", ge=MIN_DIMENSION, le=MAX_HEIGHT),
]
ImageFileField = Annotated[
    str,
    Field(description="Filename of the image in ComfyUI's input directory"),
]
ModelNameField = Annotated[
    str,
    Field(description="Checkpoint model name (leave empty for default)"),
]
NegativePromptField = Annotated[str, Field(description="What to avoid in the output")]
WaitField = Annotated[
    bool,
    Field(description="If True, block until complete and return result"),
]


def _validate_workflow_json(raw: str) -> dict[str, Any]:
    """Parse and validate workflow JSON string."""
    if len(raw.encode("utf-8")) > _MAX_WORKFLOW_JSON_BYTES:
        raise ValueError(f"Workflow JSON exceeds maximum size ({_MAX_WORKFLOW_JSON_BYTES} bytes)")
    try:
        wf = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON workflow: {e}") from e
    if not isinstance(wf, dict):
        raise ValueError("Workflow JSON must be a JSON object at the top level")
    return wf


def _validate_image_filename(filename: str, sanitizer: PathSanitizer) -> str:
    """Validate an image filename for use in workflow tools."""
    return sanitizer.validate_filename(filename)


def _format_warnings(warnings: list[str]) -> str:
    """Format warnings for user display."""
    if not warnings:
        return ""
    return "\n⚠️ Warnings detected:\n" + "\n".join(f"  - {w}" for w in warnings)


async def _submit_workflow(
    *,
    wf: dict[str, Any],
    tool_name: str,
    success_message: str,
    wait: bool,
    client: ComfyUIClient,
    audit: AuditLogger,
    inspector: WorkflowInspector,
    progress: WebSocketProgress | None,
    stream_events: bool = False,
    model_checker: ModelChecker | None = None,
    inspect_extra: dict[str, Any] | None = None,
) -> str:
    """Inspect, submit, and optionally wait for a workflow.

    Encapsulates the inspect -> audit -> submit -> wait pattern shared
    by all generation tools.
    """
    inspection = inspector.inspect(wf)
    if model_checker is not None:
        model_warnings = await model_checker.check_models(wf, client)
        if model_warnings:
            inspection.warnings.extend(model_warnings)
            if inspector.mode == "enforce":
                raise WorkflowBlockedError(f"Workflow blocked — missing models: {model_warnings}")

    log_kwargs: dict[str, Any] = {
        "tool": tool_name,
        "action": "inspected",
        "nodes_used": inspection.nodes_used,
        "warnings": inspection.warnings,
    }
    if inspect_extra:
        log_kwargs["extra"] = inspect_extra
    if model_checker is not None:
        log_kwargs["status"] = "allowed"
    await audit.async_log(**log_kwargs)

    warning_msg = _format_warnings(inspection.warnings)

    should_use_ws = wait or stream_events
    ws_client_id = progress.new_client_id() if should_use_ws and progress is not None else None
    response = await client.post_prompt(wf, client_id=ws_client_id)
    prompt_id = response.get("prompt_id", "unknown")
    await audit.async_log(tool=tool_name, action="submitted", prompt_id=prompt_id)

    if stream_events:
        if progress is None:
            raise RuntimeError("Progress tracking is not configured")
        state, events = await progress.wait_for_completion_with_events(
            prompt_id,
            client_id=ws_client_id,
        )
        await audit.async_log(
            tool=tool_name,
            action="stream_completed",
            prompt_id=prompt_id,
            extra={"status": state.status, "elapsed": state.elapsed_seconds, "events": len(events)},
        )
        result_dict = state.to_dict()
        result_dict["events"] = events
        if inspection.warnings:
            result_dict["warnings"] = inspection.warnings
        return json.dumps(result_dict)

    if wait and progress is not None:
        state = await progress.wait_for_completion(prompt_id, client_id=ws_client_id)
        await audit.async_log(
            tool=tool_name,
            action="completed",
            prompt_id=prompt_id,
            extra={"status": state.status, "elapsed": state.elapsed_seconds},
        )
        result_dict = state.to_dict()
        if inspection.warnings:
            result_dict["warnings"] = inspection.warnings
        return json.dumps(result_dict)

    return f"{success_message} prompt_id: {prompt_id}{warning_msg}"


# Default txt2img workflow — uses standard ComfyUI nodes
_DEFAULT_TXT2IMG: dict[str, dict[str, Any]] = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "bad quality, blurry", "clip": ["4", 1]},
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "comfyui-mcp", "images": ["8", 0]},
    },
}


def _build_txt2img_workflow(
    prompt: str,
    negative_prompt: str = "bad quality, blurry",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    cfg: float = 7.0,
    model: str = "",
) -> dict:
    """Build a txt2img workflow from parameters."""
    wf = copy.deepcopy(_DEFAULT_TXT2IMG)
    wf["6"]["inputs"]["text"] = prompt
    wf["7"]["inputs"]["text"] = negative_prompt
    wf["5"]["inputs"]["width"] = width
    wf["5"]["inputs"]["height"] = height
    wf["3"]["inputs"]["steps"] = steps
    wf["3"]["inputs"]["cfg"] = cfg
    if model:
        wf["4"]["inputs"]["ckpt_name"] = model
    return wf


def _format_summary(analysis: WorkflowAnalysis) -> str:
    """Format an analysis dict into a human-readable summary."""
    lines: list[str] = []

    node_count = analysis["node_count"]
    node_word = "node" if node_count == 1 else "nodes"
    lines.append(f"Workflow: {node_count} {node_word}")
    lines.append(f"Pipeline: {analysis['pipeline']}")

    if analysis["models"]:
        model_strs = [f"{m['name']} ({m['type']})" for m in analysis["models"]]
        lines.append(f"Models: {', '.join(model_strs)}")

    if analysis["flow"]:
        flow_parts: list[str] = []
        for node in analysis["flow"]:
            label = node["display_name"]
            # Add key inline params for specific node types
            ct = node["class_type"]
            inputs = node["inputs"]
            if ct == "EmptyLatentImage" and "width" in inputs and "height" in inputs:
                label += f"({inputs['width']}x{inputs['height']})"
            elif ct in _SAMPLER_NODE_TYPES:
                params = []
                if "steps" in inputs:
                    params.append(f"steps={inputs['steps']}")
                if "cfg" in inputs:
                    params.append(f"cfg={inputs['cfg']}")
                if params:
                    label += f"({', '.join(params)})"
            flow_parts.append(label)
        lines.append(f"Flow: {' -> '.join(flow_parts)}")

    for node_id in analysis["prompt_nodes"]:
        lines.append(f"Prompt: node {node_id} (CLIPTextEncode)")
    for node_id in analysis["negative_nodes"]:
        lines.append(f"Negative: node {node_id} (CLIPTextEncode)")

    if analysis["parameters"]:
        param_strs = [f"{k}={v}" for k, v in analysis["parameters"].items()]
        lines.append(f"Parameters: {', '.join(param_strs)}")

    return "\n".join(lines)


def _escape_mermaid_text(value: Any) -> str:
    """Escape text used in Mermaid node labels.

    HTML-escapes special characters so that user-controlled workflow values
    (model names, prompt text, etc.) cannot inject markup or break Mermaid
    diagrams in renderers that parse label content as HTML.
    The order matters: '&' must be replaced before '<'/'>' to avoid
    double-escaping.
    """
    text = str(value)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&#34;")
    return text.replace("\n", " ")


def _classify_node_style(class_type: str) -> str:
    """Map class types to Mermaid style categories."""
    if class_type in _SAMPLER_NODE_TYPES:
        return "sampler"
    if class_type in {"SaveImage", "PreviewImage", "SaveAnimatedWEBP", "SaveVideo"}:
        return "output"
    if "Encode" in class_type or class_type.endswith("Encoder"):
        return "encoder"
    if class_type in _INPUT_NODE_TYPES or "Loader" in class_type:
        return "loader"
    return "default"


def _format_node_subtitle(node: dict[str, Any]) -> str:
    """Build compact node subtitle with key parameters for diagram readability."""
    ct = node["class_type"]
    inputs = node["inputs"]
    if ct in {"CheckpointLoaderSimple", "CheckpointLoader"} and "ckpt_name" in inputs:
        return _escape_mermaid_text(inputs["ckpt_name"])
    if ct == "EmptyLatentImage" and "width" in inputs and "height" in inputs:
        return f"{inputs['width']}x{inputs['height']}"
    if ct in _SAMPLER_NODE_TYPES:
        parts: list[str] = []
        if "steps" in inputs:
            parts.append(f"steps={inputs['steps']}")
        if "cfg" in inputs:
            parts.append(f"cfg={inputs['cfg']}")
        return ", ".join(parts)
    if ct == "CLIPTextEncode" and "text" in inputs:
        text = _escape_mermaid_text(inputs["text"])
        return text if len(text) <= 48 else f"{text[:45]}..."
    return ""


def _edge_label_for_input(input_name: str) -> str:
    """Map ComfyUI input names to readable Mermaid edge labels."""
    mapping = {
        "model": "MODEL",
        "clip": "CLIP",
        "vae": "VAE",
        "positive": "CONDITIONING",
        "negative": "CONDITIONING",
        "latent_image": "LATENT",
        "samples": "LATENT",
        "image": "IMAGE",
        "images": "IMAGE",
    }
    return mapping.get(input_name, input_name.upper())


def _format_mermaid(analysis: WorkflowAnalysis) -> str:
    """Format an analysis dict as a Mermaid flowchart."""
    lines: list[str] = ["flowchart LR"]

    styles: dict[str, str] = {}
    for node in analysis["flow"]:
        node_id = node["node_id"]
        graph_id = f"n{node_id}"
        title = _escape_mermaid_text(node["display_name"])
        subtitle = _format_node_subtitle(node)
        label = f"{title}<br/>{subtitle}" if subtitle else title
        lines.append(f'    {graph_id}["{label}"]')
        styles[graph_id] = _classify_node_style(node["class_type"])

    node_ids = {n["node_id"] for n in analysis["flow"]}
    for node in analysis["flow"]:
        child_graph_id = f"n{node['node_id']}"
        for input_name, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                parent_id = value[0]
                if parent_id in node_ids:
                    parent_graph_id = f"n{parent_id}"
                    label = _edge_label_for_input(input_name)
                    lines.append(f"    {parent_graph_id} -->|{label}| {child_graph_id}")

    lines.extend(
        [
            "    classDef loader fill:#d9ebff,stroke:#1d4e89,color:#0b2239;",
            "    classDef sampler fill:#d8f3dc,stroke:#2d6a4f,color:#0b2818;",
            "    classDef encoder fill:#fde2c5,stroke:#b96a00,color:#3d2400;",
            "    classDef output fill:#ffd8d8,stroke:#a4161a,color:#3b090a;",
            "    classDef default fill:#eef1f4,stroke:#6b7280,color:#111827;",
        ]
    )
    for graph_id, style in styles.items():
        lines.append(f"    class {graph_id} {style};")

    return "\n".join(lines)


def register_generation_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    inspector: WorkflowInspector,
    *,
    read_limiter: RateLimiter | None = None,
    progress: WebSocketProgress | None = None,
    model_checker: ModelChecker | None = None,
    sanitizer: PathSanitizer,
) -> dict[str, Any]:
    """Register generation tools."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def comfyui_run_workflow(workflow: str, wait: bool = False) -> str:
        """Submit an arbitrary ComfyUI workflow for execution.

        Args:
            workflow: JSON string of a ComfyUI workflow (API format).
                      Each key is a node ID, each value has 'class_type' and 'inputs'.
            wait: If True, block until execution completes and return structured result
                  with status, outputs, and elapsed time. If False (default), return
                  immediately with just the prompt_id.
        """
        limiter.check("run_workflow")
        wf = _validate_workflow_json(workflow)

        return await _submit_workflow(
            wf=wf,
            tool_name="run_workflow",
            success_message="Workflow submitted.",
            wait=wait,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=progress,
            stream_events=False,
            model_checker=model_checker,
        )

    tool_fns["comfyui_run_workflow"] = comfyui_run_workflow

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def comfyui_run_workflow_stream(workflow: str) -> str:
        """Submit a ComfyUI workflow and return websocket stream events plus final status.

        Uses ComfyUI's websocket stream endpoint internally to capture per-event
        execution updates (for example, `progress`, `executing`, `executed`).
        Events are filtered by `prompt_id` when that field is present in the
        websocket payload.

        Args:
            workflow: JSON string of a ComfyUI workflow (API format).
        """
        limiter.check("run_workflow_stream")
        wf = _validate_workflow_json(workflow)

        return await _submit_workflow(
            wf=wf,
            tool_name="run_workflow_stream",
            success_message="Workflow stream started.",
            wait=False,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=progress,
            stream_events=True,
            model_checker=model_checker,
        )

    tool_fns["comfyui_run_workflow_stream"] = comfyui_run_workflow_stream

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def comfyui_generate_image(
        prompt: Annotated[str, Field(description="Text description of the image")],
        negative_prompt: NegativePromptField = "bad quality, blurry",
        width: WidthField = 512,
        height: HeightField = 512,
        steps: StepsField = 20,
        cfg: CfgField = 7.0,
        model: ModelNameField = "",
        wait: WaitField = False,
    ) -> str:
        """Generate an image from a text prompt using a default txt2img workflow."""
        limiter.check("generate_image")
        if not MIN_DIMENSION <= width <= MAX_WIDTH:
            raise ValueError(f"width must be between {MIN_DIMENSION} and {MAX_WIDTH}")
        if not MIN_DIMENSION <= height <= MAX_HEIGHT:
            raise ValueError(f"height must be between {MIN_DIMENSION} and {MAX_HEIGHT}")
        _validate_steps(steps)
        _validate_cfg(cfg)

        wf = _build_txt2img_workflow(prompt, negative_prompt, width, height, steps, cfg, model)

        return await _submit_workflow(
            wf=wf,
            tool_name="generate_image",
            success_message="Image generation started.",
            wait=wait,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=progress,
            stream_events=False,
            model_checker=model_checker,
            inspect_extra={"prompt": prompt, "width": width, "height": height},
        )

    tool_fns["comfyui_generate_image"] = comfyui_generate_image

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_summarize_workflow(
        workflow: Annotated[
            str,
            Field(
                description="JSON string of a ComfyUI workflow (API format). "
                "Each top-level key is a node ID, each value has 'class_type' and 'inputs'.",
            ),
        ],
        output_format: Annotated[
            Literal["text", "mermaid"],
            Field(
                default="text",
                description="Output format: 'text' (human-readable summary) or "
                "'mermaid' (Mermaid flowchart markup).",
            ),
        ] = "text",
    ) -> str:
        """Summarize a ComfyUI workflow's structure, data flow, and key parameters.

        Parses the workflow graph, extracts models, parameters, and execution flow.
        Enriches with display names from the ComfyUI server when available.
        """
        summary_limiter = read_limiter if read_limiter is not None else limiter
        summary_limiter.check("summarize_workflow")

        # Defense-in-depth: pydantic enforces Literal at the FastMCP boundary,
        # but direct Python callers (including tests) bypass that. Keep the
        # runtime check.
        normalized_format = output_format.lower().strip() if isinstance(output_format, str) else ""
        if normalized_format not in {"text", "mermaid"}:
            raise ValueError('output_format must be either "text" or "mermaid"')

        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e

        if not isinstance(wf, dict):
            raise ValueError("Workflow must be a JSON object keyed by node IDs")

        # Best-effort API enrichment
        object_info: dict[str, Any] | None = None
        with contextlib.suppress(httpx.HTTPError, OSError):
            object_info = await client.get_object_info()

        analysis = _analyze_workflow(wf, object_info)
        await audit.async_log(
            tool="summarize_workflow",
            action="summarized",
            extra={
                "node_count": analysis["node_count"],
                "pipeline": analysis["pipeline"],
                "output_format": normalized_format,
            },
        )
        if normalized_format == "mermaid":
            return _format_mermaid(analysis)
        return _format_summary(analysis)

    tool_fns["comfyui_summarize_workflow"] = comfyui_summarize_workflow

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def comfyui_transform_image(
        image: ImageFileField,
        prompt: Annotated[str, Field(description="Text description guiding the transformation")],
        negative_prompt: NegativePromptField = "bad quality, blurry",
        strength: StrengthField = 0.75,
        steps: StepsField = 20,
        cfg: CfgField = 7.0,
        model: ModelNameField = "",
        wait: WaitField = False,
    ) -> str:
        """Transform an existing image using a text prompt (img2img).

        The input image must already be uploaded to ComfyUI via comfyui_upload_image.
        """
        limiter.check("transform_image")
        _validate_strength(strength)
        _validate_steps(steps)
        _validate_cfg(cfg)

        clean_image = _validate_image_filename(image, sanitizer)

        params: dict[str, Any] = {
            "image": clean_image,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "denoise": strength,
            "steps": steps,
            "cfg": cfg,
        }
        if model:
            params["model"] = model

        wf = _create_from_template("img2img", params)

        return await _submit_workflow(
            wf=wf,
            tool_name="transform_image",
            success_message="Image transformation started.",
            wait=wait,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=progress,
            stream_events=False,
            inspect_extra={"image": clean_image, "prompt": prompt, "strength": strength},
        )

    tool_fns["comfyui_transform_image"] = comfyui_transform_image

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def comfyui_inpaint_image(
        image: ImageFileField,
        mask: Annotated[str, Field(description="Mask image filename (white=inpaint, black=keep)")],
        prompt: Annotated[str, Field(description="Text description for the inpainted region")],
        negative_prompt: NegativePromptField = "bad quality, blurry",
        strength: StrengthField = 0.8,
        steps: StepsField = 20,
        cfg: CfgField = 7.0,
        model: ModelNameField = "",
        wait: WaitField = False,
    ) -> str:
        """Inpaint regions of an image using a mask and text prompt.

        Both the input image and mask must already be uploaded via
        comfyui_upload_image/comfyui_upload_mask.
        White regions in the mask indicate areas to regenerate.
        """
        limiter.check("inpaint_image")
        _validate_strength(strength)
        _validate_steps(steps)
        _validate_cfg(cfg)

        clean_image = _validate_image_filename(image, sanitizer)
        clean_mask = _validate_image_filename(mask, sanitizer)

        params: dict[str, Any] = {
            "image": clean_image,
            "mask": clean_mask,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "denoise": strength,
            "steps": steps,
            "cfg": cfg,
        }
        if model:
            params["model"] = model

        wf = _create_from_template("inpaint", params)

        return await _submit_workflow(
            wf=wf,
            tool_name="inpaint_image",
            success_message="Inpainting started.",
            wait=wait,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=progress,
            stream_events=False,
            inspect_extra={"image": clean_image, "mask": clean_mask, "prompt": prompt},
        )

    tool_fns["comfyui_inpaint_image"] = comfyui_inpaint_image

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    async def comfyui_upscale_image(
        image: ImageFileField,
        upscale_model: Annotated[
            str,
            Field(
                description="Name of the upscale model file. "
                "Use comfyui_list_models with folder='upscale_models' "
                "to see available models."
            ),
        ] = "RealESRGAN_x4plus.pth",
        wait: WaitField = False,
    ) -> str:
        """Upscale an image using a model-based upscaler.

        The input image must already be uploaded to ComfyUI via comfyui_upload_image.
        The scale factor is determined by the upscale model (e.g. RealESRGAN_x4plus = 4x).
        """
        limiter.check("upscale_image")
        clean_image = _validate_image_filename(image, sanitizer)

        wf = _create_from_template("upscale", {"image": clean_image, "model_name": upscale_model})

        return await _submit_workflow(
            wf=wf,
            tool_name="upscale_image",
            success_message="Upscaling started.",
            wait=wait,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=progress,
            stream_events=False,
            inspect_extra={"image": clean_image, "upscale_model": upscale_model},
        )

    tool_fns["comfyui_upscale_image"] = comfyui_upscale_image

    return tool_fns
