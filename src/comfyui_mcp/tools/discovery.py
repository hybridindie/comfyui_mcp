"""Discovery tools: list_models, list_nodes, get_node_info, list_workflows."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.pagination import LimitField, OffsetField, PaginationEnvelope, paginate
from comfyui_mcp.security.node_auditor import NodeAuditor
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer

_SUPPORTED_MODEL_FAMILIES = {"sd15", "sdxl", "flux", "sd3", "cascade"}

_MODEL_FAMILY_ALIASES = {
    "sd1.5": "sd15",
    "sd 1.5": "sd15",
    "stable-diffusion-1.5": "sd15",
    "stable diffusion 1.5": "sd15",
    "stable_diffusion_1_5": "sd15",
    "stable-diffusion-xl": "sdxl",
    "stable diffusion xl": "sdxl",
    "stable_diffusion_xl": "sdxl",
    "flux.1": "flux",
    "sd3.5": "sd3",
    "stable-cascade": "cascade",
}

_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "sd15": {
        "recommended": {
            "sampler": "euler_ancestral",
            "scheduler": "normal",
            "steps": 28,
            "cfg": 7.0,
            "resolution": "512x768",
            "clip_skip": 1,
            "notes": "Tag-heavy prompts and negative prompts work well.",
        }
    },
    "sdxl": {
        "recommended": {
            "sampler": "dpmpp_2m",
            "scheduler": "karras",
            "steps": 30,
            "cfg": 5.5,
            "resolution": "1024x1024",
            "clip_skip": 1,
            "notes": "Prefer natural language prompts with clear scene composition.",
        }
    },
    "flux": {
        "recommended": {
            "sampler": "euler",
            "scheduler": "simple",
            "steps": 20,
            "cfg": 1.0,
            "resolution": "1024x1024",
            "clip_skip": 1,
            "notes": "Flow-matching models expect low CFG and concise language.",
        }
    },
    "sd3": {
        "recommended": {
            "sampler": "dpmpp_2m",
            "scheduler": "sgm_uniform",
            "steps": 28,
            "cfg": 4.5,
            "resolution": "1024x1024",
            "clip_skip": 1,
            "notes": "Use detailed, descriptive prompts; avoid over-weighting terms.",
        }
    },
    "cascade": {
        "recommended": {
            "sampler": "dpmpp_2m",
            "scheduler": "simple",
            "steps": 24,
            "cfg": 4.0,
            "resolution": "1024x1024",
            "clip_skip": 1,
            "notes": "Cascade benefits from broad composition instructions first.",
        }
    },
}

_PROMPTING_GUIDES: dict[str, dict[str, Any]] = {
    "sd15": {
        "prompt_structure": "subject, style, lighting, lens/composition, quality tags",
        "weight_syntax": "(token:1.2)",
        "quality_tags": ["masterpiece", "best quality", "high detail"],
        "negative_prompt_tips": "Use negatives for anatomy artifacts and low-quality tokens.",
    },
    "sdxl": {
        "prompt_structure": "subject + environment + mood + camera framing",
        "weight_syntax": "(token:1.1)",
        "quality_tags": ["cinematic lighting", "high detail", "sharp focus"],
        "negative_prompt_tips": "Keep negatives shorter than SD1.5 to avoid over-constraining.",
    },
    "flux": {
        "prompt_structure": "natural language sentence describing subject, setting, and style",
        "weight_syntax": "Avoid heavy weighting unless necessary",
        "quality_tags": ["natural lighting", "detailed texture"],
        "negative_prompt_tips": "Use short negatives only for hard constraints (e.g. watermark).",
    },
    "sd3": {
        "prompt_structure": "clear scene description with explicit style and camera intent",
        "weight_syntax": "Light weighting only; rely on plain language first",
        "quality_tags": ["balanced composition", "fine detail"],
        "negative_prompt_tips": (
            "Use focused negatives for specific defects, not long keyword lists."
        ),
    },
    "cascade": {
        "prompt_structure": "high-level composition first, then style modifiers",
        "weight_syntax": "(token:1.1) for minor emphasis",
        "quality_tags": ["clean composition", "color harmony"],
        "negative_prompt_tips": "Keep negatives concise; tune guidance before adding many tokens.",
    },
}


def _normalize_model_family(model_family: str) -> str:
    key = model_family.strip().lower()
    return _MODEL_FAMILY_ALIASES.get(key, key)


def _infer_model_family(model_name: str) -> str | None:
    name = model_name.strip().lower()
    checks = [
        ("flux", "flux"),
        ("sdxl", "sdxl"),
        ("sd3", "sd3"),
        ("cascade", "cascade"),
        ("dreamshaper", "sd15"),
        ("anything", "sd15"),
    ]
    for needle, family in checks:
        if needle in name:
            return family
    return None


def register_discovery_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    sanitizer: PathSanitizer,
    node_auditor: NodeAuditor | None = None,
) -> dict[str, Any]:
    """Register discovery tools and return a dict of callable functions for testing."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_list_models(
        folder: str = "checkpoints",
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> PaginationEnvelope[str]:
        """List available models in a folder (checkpoints, loras, vae, etc.).

        Args:
            folder: Model folder type (checkpoints, loras, vae, etc.)
            limit: Maximum number of results to return (default: 25, max: 100)
            offset: Starting index for pagination (default: 0)
        """
        sanitizer.validate_path_segment(folder, label="folder")
        models = await client.get_models(folder)
        return paginate(models, offset, limit, default_limit=25, max_limit=100)

    tool_fns["comfyui_list_models"] = comfyui_list_models

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_list_models_detailed(
        folder: str = "checkpoints",
    ) -> dict[str, Any]:
        """List models in a folder with file metadata (name, pathIndex, modified, created, size).

        Uses the /experiment/models/{folder} endpoint (#143). Use this when you
        need the pathIndex (for preview lookups) or file sizes; use
        comfyui_list_models for a bare-name listing.

        Args:
            folder: Model folder type (checkpoints, loras, vae, etc.)
        """
        sanitizer.validate_path_segment(folder, label="folder")
        await audit.async_log(
            tool="list_models_detailed", action="called", extra={"folder": folder}
        )
        models = await client.get_models_detailed(folder)
        return {"folder": folder, "models": models, "count": len(models)}

    tool_fns["comfyui_list_models_detailed"] = comfyui_list_models_detailed

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_model_preview(
        folder: Annotated[str, Field(description="Model folder (checkpoints, loras, etc.)")],
        path_index: Annotated[
            int, Field(description="pathIndex from comfyui_list_models_detailed", ge=0)
        ],
        filename: Annotated[str, Field(description="Model filename")],
    ) -> dict[str, Any]:
        """Fetch a model's preview image via /experiment/models/preview (\\#143).

        Returns the preview as base64-encoded image data with a mime_type, or
        {"available": false} when the model has no preview (404).

        Args:
            folder: Model folder type.
            path_index: The pathIndex from comfyui_list_models_detailed.
            filename: The model filename.
        """
        sanitizer.validate_path_segment(folder, label="folder")
        if not filename or "\x00" in filename or ".." in filename:
            raise ValueError(f"filename is invalid: {filename!r}")
        await audit.async_log(
            tool="get_model_preview",
            action="called",
            extra={"folder": folder, "path_index": path_index, "filename": filename},
        )
        import base64

        try:
            r = await client.get_model_preview(folder, path_index, filename)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"available": False, "folder": folder, "filename": filename}
            raise
        content_type = r.headers.get("content-type", "application/octet-stream")
        data = r.content
        encoded = base64.b64encode(data).decode("ascii")
        return {
            "available": True,
            "folder": folder,
            "filename": filename,
            "mime_type": content_type,
            "size_bytes": len(data),
            "data_base64": encoded,
        }

    tool_fns["comfyui_get_model_preview"] = comfyui_get_model_preview

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_list_nodes(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> PaginationEnvelope[str]:
        """List all available ComfyUI node types.

        Args:
            limit: Maximum number of results to return (default: 25, max: 100)
            offset: Starting index for pagination (default: 0)
        """
        info = await client.get_object_info()
        return paginate(sorted(info.keys()), offset, limit, default_limit=25, max_limit=100)

    tool_fns["comfyui_list_nodes"] = comfyui_list_nodes

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_node_info(
        node_class: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Node class name (e.g. 'KSampler', 'CLIPTextEncode'). "
                "Use comfyui_list_nodes to discover available class names.",
            ),
        ],
    ) -> dict[str, Any]:
        """Get the input/output schema and metadata for a single ComfyUI node type.

        Returns a dict with keys: input, input_order, is_input_list, output,
        output_is_list, output_name, name, display_name, description, python_module,
        category, output_node, search_aliases, plus optional flags like deprecated,
        experimental, and api_node when set on the node.
        """
        return await client.get_object_info(node_class)

    tool_fns["comfyui_get_node_info"] = comfyui_get_node_info

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_list_workflows(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> PaginationEnvelope[dict[str, Any]]:
        """List workflow templates registered on the ComfyUI server (the
        ``/workflow_templates`` endpoint, populated by installed front-end packages).

        This is distinct from ``comfyui_create_workflow``'s built-in template names
        (txt2img, img2img, etc.) which are hard-coded in the MCP for graph generation.

        Returns a paginated envelope: ``{items, total, offset, limit, has_more}``.
        Each item is ``{"package": str, "templates": [...]}`` from the server.
        """
        templates_by_package = await client.get_workflow_templates()
        # client.get_workflow_templates returns dict[package_name, list[template]];
        # flatten to a list of {package, templates} so paginate() can slice it.
        items = [
            {"package": package, "templates": templates}
            for package, templates in (templates_by_package or {}).items()
        ]
        return paginate(items, offset, limit, default_limit=25, max_limit=100)

    tool_fns["comfyui_list_workflows"] = comfyui_list_workflows

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_list_extensions(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> PaginationEnvelope[str]:
        """List installed ComfyUI extensions (front-end / back-end JavaScript modules
        registered with the ComfyUI server).

        Returns a paginated envelope: ``{items, total, offset, limit, has_more}``.
        Each item is the extension's URL/path string.
        """
        extensions = await client.get_extensions()
        return paginate(extensions, offset, limit, default_limit=25, max_limit=100)

    tool_fns["comfyui_list_extensions"] = comfyui_list_extensions

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_server_features() -> dict[str, Any]:
        """Get the feature flags advertised by the ComfyUI server.

        Returns the raw ``/features`` response — typically a dict of
        {feature_name: bool}. Useful for capability-based branching, e.g.
        checking ``supports_preview_metadata`` before requesting preview-format
        images via ``comfyui_get_image``.
        """
        return await client.get_features()

    tool_fns["comfyui_get_server_features"] = comfyui_get_server_features

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_list_model_folders(
        limit: LimitField = 25,
        offset: OffsetField = 0,
    ) -> PaginationEnvelope[str]:
        """List the model-folder types ComfyUI recognizes (checkpoints, loras, vae,
        controlnet, etc.). Pass any returned name as the ``folder`` argument to
        ``comfyui_list_models`` or ``comfyui_get_model_metadata``.

        Returns a paginated envelope: ``{items, total, offset, limit, has_more}``.
        """
        folders = await client.get_model_types()
        return paginate(folders, offset, limit, default_limit=25, max_limit=100)

    tool_fns["comfyui_list_model_folders"] = comfyui_list_model_folders

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_model_metadata(folder: str, filename: str) -> dict[str, Any]:
        """Get metadata for a model file.

        Args:
            folder: Model folder type (checkpoints, loras, vae, etc.)
            filename: Name of the model file
        """
        sanitizer.validate_path_segment(folder, label="folder")
        sanitizer.validate_path_segment(filename, label="filename")
        return await client.get_view_metadata(folder, filename)

    tool_fns["comfyui_get_model_metadata"] = comfyui_get_model_metadata

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_audit_dangerous_nodes() -> dict[str, Any]:
        """Audit all installed nodes to identify potentially dangerous ones.

        Scans for nodes that could execute arbitrary code, run shell commands,
        or access the file system. Useful for building a dangerous node blacklist.

        Returns:
            Dictionary with dangerous and suspicious node counts and lists
        """
        await audit.async_log(tool="audit_dangerous_nodes", action="started")

        auditor = node_auditor if node_auditor else NodeAuditor()

        object_info = await client.get_object_info()
        result = auditor.audit_all_nodes(object_info)

        output = {
            "total_nodes": result.total_nodes,
            "dangerous": {
                "count": result.dangerous_count,
                "nodes": [
                    {"class": n.node_class, "reason": n.reason} for n in result.dangerous_nodes
                ],
            },
            "suspicious": {
                "count": result.suspicious_count,
                "nodes": [
                    {"class": n.node_class, "reason": n.reason} for n in result.suspicious_nodes
                ],
            },
        }

        await audit.async_log(
            tool="audit_dangerous_nodes",
            action="completed",
            extra={
                "total": result.total_nodes,
                "dangerous": result.dangerous_count,
                "suspicious": result.suspicious_count,
            },
        )
        return output

    tool_fns["comfyui_audit_dangerous_nodes"] = comfyui_audit_dangerous_nodes

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_system_info() -> dict[str, Any]:
        """Return sanitized ComfyUI system information.

        Returns a whitelist-filtered subset of system stats useful for making
        generation decisions: GPU VRAM, queue depth, and ComfyUI version.
        Sensitive fields (hostname, OS, CPU details, file paths, Python version,
        network interfaces) are deliberately excluded.

        Returns:
            Dictionary with keys: comfyui_version, devices (list of GPU info),
            queue (running/pending counts).
        """

        raw, queue_raw = await asyncio.gather(
            client.get_system_stats(),
            client.get_queue(),
        )

        # Whitelist: only forward fields that are safe to expose
        devices: list[dict] = []
        for device in raw.get("devices", []):
            if not isinstance(device, dict):
                continue
            entry: dict = {}
            if "name" in device:
                entry["name"] = str(device["name"])
            vram_total = device.get("vram_total")
            vram_free = device.get("vram_free")
            if isinstance(vram_total, int | float):
                entry["vram_total_mb"] = round(vram_total / (1024 * 1024))
            if isinstance(vram_free, int | float):
                entry["vram_free_mb"] = round(vram_free / (1024 * 1024))
            if "torch_vram_total" in device and isinstance(device["torch_vram_total"], int | float):
                entry["torch_vram_total_mb"] = round(device["torch_vram_total"] / (1024 * 1024))
            if "torch_vram_free" in device and isinstance(device["torch_vram_free"], int | float):
                entry["torch_vram_free_mb"] = round(device["torch_vram_free"] / (1024 * 1024))
            if entry:
                devices.append(entry)

        running = len(queue_raw.get("queue_running", []))
        pending = len(queue_raw.get("queue_pending", []))

        result: dict = {
            "comfyui_version": str(raw.get("system", {}).get("comfyui_version", "unknown")),
            "devices": devices,
            "queue": {"running": running, "pending": pending},
        }
        return result

    tool_fns["comfyui_get_system_info"] = comfyui_get_system_info

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    async def comfyui_get_model_presets(
        model_name: str | None = None,
        model_family: str | None = None,
    ) -> dict[str, Any]:
        """Get recommended generation presets for a model family.

        The presets are static data baked into this MCP — they reflect
        community best-practice defaults, not anything the connected ComfyUI
        server reports. At least one of ``model_name`` or ``model_family``
        must be supplied; if both are given, ``model_family`` takes
        precedence and ``model_name`` is ignored.

        Args:
            model_name (required if ``model_family`` is omitted): Model
                filename to auto-detect the family from (e.g.
                ``sd_xl_base_1.0.safetensors`` → ``sdxl``). Used as a
                fallback when ``model_family`` is empty.
            model_family (required if ``model_name`` is omitted): Explicit
                family identifier. Valid values: ``sd15``, ``sdxl``,
                ``flux``, ``sd3``, ``cascade`` (aliases like ``sd1.5``,
                ``stable-diffusion-xl``, ``flux.1``, ``sd3.5``,
                ``stable-cascade`` are also accepted).

        Returns:
            Dict ``{"family": "<id>", "recommended": {<settings>}}`` where
            ``recommended`` always contains the keys ``sampler`` (str),
            ``scheduler`` (str), ``steps`` (int), ``cfg`` (float),
            ``resolution`` (str like ``"1024x1024"``), ``clip_skip`` (int),
            and ``notes`` (str). Callers that only need the settings can
            read ``result["recommended"]`` directly.
        """

        family: str | None = None
        if model_family:
            family = _normalize_model_family(model_family)
        elif model_name:
            family = _infer_model_family(model_name)
            if family is None:
                raise ValueError(f"Could not infer model family from: {model_name}")
        else:
            raise ValueError("Provide either model_name or model_family")

        if family not in _SUPPORTED_MODEL_FAMILIES:
            supported = ", ".join(sorted(_SUPPORTED_MODEL_FAMILIES))
            raise ValueError(f"Unknown model family: {family}. Supported families: {supported}")

        return {
            "family": family,
            **_MODEL_PRESETS[family],
        }

    tool_fns["comfyui_get_model_presets"] = comfyui_get_model_presets

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    async def comfyui_get_prompting_guide(model_family: str) -> dict[str, Any]:
        """Get the prompting guide for a model family.

        The guide is static data baked into this MCP — it gives stylistic
        and structural advice tuned to each family (prompt structure,
        weighting syntax conventions, recommended quality tags, negative
        prompt tips). It does not reflect the connected ComfyUI server's
        installed models or state.

        Args:
            model_family (required): Family identifier. Valid values:
                ``sd15``, ``sdxl``, ``flux``, ``sd3``, ``cascade`` (aliases
                like ``sd1.5``, ``stable-diffusion-xl``, ``flux.1``,
                ``sd3.5``, ``stable-cascade`` are also accepted).

        Returns:
            Dict ``{"family": "<id>", "guide": {<advice>}}`` where ``guide``
            always contains the keys ``prompt_structure`` (str),
            ``weight_syntax`` (str), ``quality_tags`` (list[str]), and
            ``negative_prompt_tips`` (str). Callers that only need the
            advice can read ``result["guide"]`` directly.
        """
        normalized = _normalize_model_family(model_family)

        if normalized not in _SUPPORTED_MODEL_FAMILIES:
            supported = ", ".join(sorted(_SUPPORTED_MODEL_FAMILIES))
            raise ValueError(f"Unknown model family: {normalized}. Supported families: {supported}")

        return {
            "family": normalized,
            "guide": _PROMPTING_GUIDES[normalized],
        }

    tool_fns["comfyui_get_prompting_guide"] = comfyui_get_prompting_guide

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_list_subgraphs() -> dict[str, Any]:
        """List available reusable subgraph templates from ComfyUI (#144).

        Subgraphs are packaged node groups that can be inserted into a
        workflow as a single unit. Use ``comfyui_get_subgraph`` to fetch
        the actual graph JSON for a specific subgraph.

        Returns:
            Dict with ``subgraphs`` (mapping of entry IDs to metadata) and
            ``count``.
        """
        subgraphs = await client.get_global_subgraphs()
        return {"subgraphs": subgraphs, "count": len(subgraphs)}

    tool_fns["comfyui_list_subgraphs"] = comfyui_list_subgraphs

    @mcp.tool(
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        )
    )
    async def comfyui_get_subgraph(
        subgraph_id: Annotated[
            str,
            Field(
                description="Subgraph entry ID from comfyui_list_subgraphs",
                min_length=1,
            ),
        ],
    ) -> dict[str, Any]:
        """Fetch a single subgraph's JSON for inspection or insertion (#144).

        The ``data`` field in the response contains the subgraph's node map
        as a JSON string. The workflow inspector recurses into this node
        map when a subgraph node is submitted in a workflow (#110).

        Args:
            subgraph_id: The entry ID from ``comfyui_list_subgraphs``.

        Returns:
            The subgraph metadata + ``data`` (node map JSON string), or
            ``{"available": false}`` if the subgraph ID does not exist.
        """
        sanitizer.validate_path_segment(subgraph_id, label="subgraph_id")
        try:
            subgraph = await client.get_global_subgraph(subgraph_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"available": False, "subgraph_id": subgraph_id}
            raise
        return subgraph

    tool_fns["comfyui_get_subgraph"] = comfyui_get_subgraph

    return tool_fns
