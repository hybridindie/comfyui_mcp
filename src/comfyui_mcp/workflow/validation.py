"""Workflow validation: structural checks, server checks, and security inspection."""

from __future__ import annotations

import asyncio
import contextlib
import graphlib
import logging
from typing import Any, TypedDict

import httpx

from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.model_registry import MODEL_LOADER_FIELDS, get_single_field_loaders
from comfyui_mcp.security.inspector import WorkflowBlockedError, WorkflowInspector
from comfyui_mcp.workflow.types import Workflow

_logger = logging.getLogger(__name__)

# Derived view for analyze_workflow: single-field loaders only
_SINGLE_FIELD_LOADERS = get_single_field_loaders()

INPUT_NODE_TYPES = {"LoadImage", "LoadImageMask", "EmptyLatentImage"}
SAMPLER_NODE_TYPES = {"KSampler", "KSamplerAdvanced", "SamplerCustom"}
# Core output nodes used to identify terminal nodes for loop-escape analysis.
OUTPUT_NODE_TYPES = {
    "SaveImage",
    "SaveImageWebsocket",
    "SaveAnimatedWEBP",
    "SaveAnimatedPNG",
    "VHS_VideoCombine",
    "SaveVIDEO",
    "SaveAudio",
}

# Loop-boundary node types (upstream Generic Loops, CORE-14 —
# comfy_extras/nodes_loop.py). The upstream schema carries loop_boundary on
# Schema, but /object_info does not expose it; these four class_types are the
# complete set shipped by core. Detecting by name keeps the check working on
# servers that predate the schema plumbing.
LOOP_START_TYPES = frozenset({"StartLoop"})
LOOP_END_TYPES = frozenset({"EndLoop"})


class WorkflowAnalysis(TypedDict):
    """Structured result from analyze_workflow."""

    node_count: int
    class_types: list[str]
    flow: list[dict[str, Any]]
    models: list[dict[str, str]]
    parameters: dict[str, Any]
    pipeline: str
    prompt_nodes: list[str]
    negative_nodes: list[str]


def _is_link(value: Any) -> bool:
    """True when an input value is a node link [node_id, output_slot].

    Matches upstream comfy_execution.graph_utils.is_link: the slot must be an
    int/float. V3 nodes (DynamicCombo et al.) use list values with non-slot
    second elements — those are widget payloads, not links. Exported for the
    operation/summarize code paths that classify input values the same way.
    """
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], (int, float))
    )


def _link_source(value: Any) -> str | None:
    """The node id an input link points at, or None if not a link."""
    if _is_link(value):
        source = value[0]
        # isinstance check inside _is_link guarantees a str, but mypy needs
        # the explicit narrow over the NodeInputValue union.
        return source if isinstance(source, str) else None
    return None


def _parent_map(workflow: Workflow) -> dict[str, set[str]]:
    parents: dict[str, set[str]] = {node_id: set() for node_id in workflow}
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        parents.setdefault(node_id, set())
        inputs = node_data.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for value in inputs.values():
            source = _link_source(value)
            if source is not None and source in workflow:
                parents[node_id].add(source)
    return parents


def _walk(
    start_ids: set[str],
    edges: dict[str, set[str]],
    *,
    stops: set[str] | frozenset[str] = frozenset(),
) -> set[str]:
    """Reachable node ids from start_ids via edges, stopping at stops."""
    found: set[str] = set()
    pending = list(start_ids)
    while pending:
        node_id = pending.pop()
        if node_id in found:
            continue
        found.add(node_id)
        if node_id in stops:
            continue
        pending.extend(edges.get(node_id, ()))
    return found


def _collect_loop_classes(
    workflow: Workflow, object_info: dict[str, Any] | None
) -> tuple[set[str], set[str]]:
    """(start_ids, end_ids) for loop-boundary nodes present in the workflow.

    Preferred source is the server's loop_boundary metadata when present
    (newer object_info); falls back to the known core loop classes.
    """
    starts: set[str] = set()
    ends: set[str] = set()
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        ct = node_data.get("class_type", "")
        info = (object_info or {}).get(ct) or {}
        boundary = info.get("loop_boundary")
        if boundary == "start":
            starts.add(node_id)
        elif boundary == "end":
            ends.add(node_id)
        elif ct in LOOP_START_TYPES and (object_info is None or ct in object_info):
            starts.add(node_id)
        elif ct in LOOP_END_TYPES and (object_info is None or ct in object_info):
            ends.add(node_id)
    return starts, ends


def validate_loop_structure(
    workflow: Workflow,
    starts: set[str],
    ends: set[str],
    output_ids: set[str],
) -> list[str]:
    """Loop-structure validation, a port of upstream
    comfy_execution.validation.validate_loops (CORE-14) to error strings.

    Errors (mirroring upstream loop_error_type values):
    - ``loop_end_without_start``: an EndLoop with no ancestor StartLoop, or an
      EndLoop reached after its Start was already paired
    - ``loop_start_without_end``: a StartLoop that cannot pair with an EndLoop
    - ``ambiguous_loop_nesting``: an EndLoop that multiple unrelated StartLoops
      could close
    - ``loop_escape``: a loop body that reaches another EndLoop, an unpaired
      boundary, or a terminal output without passing through its own EndLoop
    - ``loop_accumulate_from_body``: EndLoop.accumulate driven by a node inside
      its own body (or by the StartLoop itself)
    """
    errors: list[str] = []
    if not starts and not ends:
        return errors

    parents: dict[str, set[str]] = _parent_map(workflow)
    children: dict[str, set[str]] = {node_id: set() for node_id in workflow}
    for node_id, node_parents in parents.items():
        for parent_id in node_parents:
            children.setdefault(parent_id, set()).add(node_id)

    terminal_outputs = {node_id for node_id in output_ids if not children.get(node_id)}

    # Start DAG: descendants of each Start, stopping at other Starts.
    start_dag = {start_id: _walk(children[start_id], children, stops=starts) for start_id in starts}
    start_descendants = {start_id: _walk(start_dag[start_id], start_dag) for start_id in starts}

    # End DAG (reverse direction): ancestors of each End, stopping at other
    # Ends. Its leaves are the innermost Ends and pair first.
    end_dag = {end_id: _walk(parents[end_id], parents, stops=ends) for end_id in ends}

    pairs: dict[str, str] = {}
    remaining_starts = set(starts)
    remaining_ends = set(ends)
    while remaining_ends:
        # Innermost unpaired end: no other unpaired end among its ancestors.
        end_id = next(
            node_id for node_id in sorted(remaining_ends) if not end_dag[node_id] & remaining_ends
        )

        candidates = _walk(parents[end_id], parents, stops=remaining_starts) & remaining_starts
        if not candidates:
            errors.append(f"Node '{end_id}': End Loop has no Start Loop (loop_end_without_start)")
            remaining_ends.discard(end_id)
            continue

        closest = {
            candidate
            for candidate in candidates
            if all(
                other == candidate or candidate in start_descendants[other] for other in candidates
            )
        }
        if len(closest) != 1:
            errors.append(
                f"Node '{end_id}': End Loop can close multiple unrelated Start Loops: "
                f"{', '.join(sorted(candidates))} (ambiguous_loop_nesting)"
            )
            remaining_ends.discard(end_id)
            continue

        start_id = closest.pop()
        pairs[start_id] = end_id
        remaining_starts.discard(start_id)
        remaining_ends.discard(end_id)

        # Escape check: previously paired Ends (none remain) may be crossed; an
        # unpaired End, a terminal output, or the loop's own End stops the
        # walk. Anything reached and stopped that isn't the paired End is an
        # escape; anything reached but NOT stopped reached past all stops.
        escaped = _walk(
            children[start_id],
            children,
            stops=remaining_ends | terminal_outputs | {end_id},
        )
        escapes = (escaped & terminal_outputs) | (escaped & (ends - {end_id} - remaining_ends))
        if escapes:
            errors.append(
                f"Node '{start_id}': loop body escapes via {', '.join(sorted(escapes))} "
                f"without passing through End Loop '{end_id}' (loop_escape)"
            )

    for start_id in sorted(remaining_starts):
        errors.append(f"Node '{start_id}': Start Loop has no End Loop (loop_start_without_end)")

    for start_id, end_id in pairs.items():
        body = _walk(children[start_id], children, stops={end_id})
        body.discard(end_id)
        body.discard(start_id)
        end_node = workflow.get(end_id)
        accumulate = (
            end_node.get("inputs", {}).get("accumulate") if isinstance(end_node, dict) else None
        )
        accumulate_source = _link_source(accumulate)
        if accumulate_source is not None and (
            accumulate_source == start_id or accumulate_source in body
        ):
            errors.append(
                f"Node '{end_id}': End Loop accumulate is driven by loop node "
                f"'{accumulate_source}' inside its own loop body "
                "(loop_accumulate_from_body)"
            )

    return errors


def _reverse(edges: dict[str, set[str]]) -> dict[str, set[str]]:
    rev: dict[str, set[str]] = {k: set() for k in edges}
    for src, dsts in edges.items():
        for dst in dsts:
            rev.setdefault(dst, set()).add(src)
    return rev


def analyze_workflow(
    workflow: Workflow, object_info: dict[str, Any] | None = None
) -> WorkflowAnalysis:
    """Analyze a ComfyUI workflow and return structured data."""
    if not workflow:
        return {
            "node_count": 0,
            "class_types": [],
            "flow": [],
            "models": [],
            "parameters": {},
            "pipeline": "unknown",
            "prompt_nodes": [],
            "negative_nodes": [],
        }

    deps: dict[str, set[str]] = {}
    node_info: dict[str, dict[str, Any]] = {}

    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        class_type = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})
        if not isinstance(inputs, dict):
            inputs = {}
        deps.setdefault(node_id, set())

        display_name = class_type
        if object_info and class_type in object_info:
            # Use the upstream display_name only if it's truthy — ComfyUI servers
            # occasionally return ``{"display_name": None}`` or an empty string,
            # which would otherwise propagate downstream and break string joins.
            display_name = object_info[class_type].get("display_name") or class_type

        node_info[node_id] = {
            "node_id": node_id,
            "class_type": class_type,
            "display_name": display_name,
            "inputs": inputs,
        }

        for value in inputs.values():
            source = _link_source(value)
            if source is not None and source in workflow:
                deps[node_id].add(source)
                deps.setdefault(source, set())

    sorter = graphlib.TopologicalSorter(deps)
    try:
        sorted_ids = list(sorter.static_order())
    except graphlib.CycleError:
        sorted_ids = list(node_info.keys())

    flow = [node_info[nid] for nid in sorted_ids if nid in node_info]
    class_types = [n["class_type"] for n in flow]

    models: list[dict[str, str]] = []
    for node in flow:
        ct = node["class_type"]
        if ct in _SINGLE_FIELD_LOADERS:
            key, folder = _SINGLE_FIELD_LOADERS[ct]
            name = node["inputs"].get(key, "")
            if name:
                models.append({"name": name, "type": folder})

    parameters: dict[str, Any] = {}
    for node in flow:
        ct = node["class_type"]
        if ct in SAMPLER_NODE_TYPES:
            for k in ("steps", "cfg", "sampler_name", "scheduler", "denoise"):
                if k in node["inputs"]:
                    param_key = "sampler" if k == "sampler_name" else k
                    parameters[param_key] = node["inputs"][k]
        if ct == "EmptyLatentImage":
            for k in ("width", "height"):
                if k in node["inputs"]:
                    parameters[k] = node["inputs"][k]

    prompt_nodes = []
    negative_nodes = []
    for node in flow:
        if node["class_type"] == "CLIPTextEncode":
            is_negative = False
            for other in flow:
                if other["class_type"] in SAMPLER_NODE_TYPES:
                    neg_link = other["inputs"].get("negative")
                    if isinstance(neg_link, list) and neg_link[0] == node["node_id"]:
                        is_negative = True
                        break
            if is_negative:
                negative_nodes.append(node["node_id"])
            else:
                prompt_nodes.append(node["node_id"])

    has_load_image = any(ct in INPUT_NODE_TYPES - {"EmptyLatentImage"} for ct in class_types)
    has_empty_latent = "EmptyLatentImage" in class_types
    has_upscale = any("Upscale" in ct for ct in class_types)

    if has_load_image:
        pipeline = "img2img"
    elif has_empty_latent:
        pipeline = "txt2img"
    else:
        pipeline = "unknown"
    if has_upscale:
        pipeline = f"{pipeline} -> upscale" if pipeline != "unknown" else "upscale"

    return {
        "node_count": len(flow),
        "class_types": class_types,
        "flow": flow,
        "models": models,
        "parameters": parameters,
        "pipeline": pipeline,
        "prompt_nodes": prompt_nodes,
        "negative_nodes": negative_nodes,
    }


async def validate_workflow(
    workflow: Workflow,
    client: ComfyUIClient,
    inspector: WorkflowInspector,
) -> dict[str, Any]:
    """Validate a workflow: structural checks, server checks, security inspection.

    Returns dict with: valid (bool), errors (list), warnings (list),
    node_count (int), pipeline (str).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Structural checks ---
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            errors.append(f"Node '{node_id}': not a valid node object")
            continue
        if "class_type" not in node_data:
            errors.append(f"Node '{node_id}': missing 'class_type'")
        inputs = node_data.get("inputs")
        if inputs is None:
            errors.append(f"Node '{node_id}': missing 'inputs'")
            continue
        if not isinstance(inputs, dict):
            errors.append(
                f"Node '{node_id}': 'inputs' must be an object, got {type(inputs).__name__}"
            )
            continue
        for input_name, value in inputs.items():
            ref_id = _link_source(value)
            if ref_id and ref_id not in workflow:
                errors.append(
                    f"Node '{node_id}' input '{input_name}':"
                    f" references non-existent node '{ref_id}'"
                )

    # Cycle detection
    deps: dict[str, set[str]] = {}
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        deps.setdefault(node_id, set())
        inputs = node_data.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for value in inputs.values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0] in workflow
            ):
                deps[node_id].add(value[0])
                deps.setdefault(value[0], set())

    sorter = graphlib.TopologicalSorter(deps)
    try:
        list(sorter.static_order())
    except graphlib.CycleError as e:
        errors.append(f"Workflow contains a cycle: {e}")

    # --- Server checks (best-effort, skip if structural errors already found) ---
    object_info: dict[str, Any] | None = None
    if not errors:
        with contextlib.suppress(httpx.HTTPError, OSError):
            object_info = await client.get_object_info()

    if errors:
        pass  # Skip server checks — structural errors already found
    elif object_info is None:
        warnings.append("ComfyUI server unreachable — server validation skipped")
    else:
        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue
            ct = node_data.get("class_type", "")
            if ct and ct not in object_info:
                errors.append(f"Node '{node_id}': class_type '{ct}' not installed on server")

        # Check models exist — batch by folder, fetch in parallel
        folder_models: dict[str, list[tuple[str, str]]] = {}
        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue
            ct = node_data.get("class_type", "")
            if ct in MODEL_LOADER_FIELDS:
                inputs = node_data.get("inputs")
                if not isinstance(inputs, dict):
                    continue
                for input_key, folder in MODEL_LOADER_FIELDS[ct]:
                    model_name = inputs.get(input_key, "")
                    if isinstance(model_name, str) and model_name:
                        folder_models.setdefault(folder, []).append((node_id, model_name))

        async def _fetch_folder(folder: str) -> tuple[str, list[str]]:
            try:
                return folder, await client.get_models(folder)
            except (httpx.HTTPError, OSError):
                return folder, []

        folder_results = dict(await asyncio.gather(*[_fetch_folder(f) for f in folder_models]))

        for folder, checks in folder_models.items():
            available = folder_results.get(folder, [])
            for node_id, model_name in checks:
                if available and model_name not in available:
                    warnings.append(
                        f"Node '{node_id}': model '{model_name}' not found in '{folder}'"
                    )

    # --- Security inspection ---
    # Fetch server-side node replacement map (#111). The server rewrites
    # class_types before validation, so what executes may differ from what we
    # vet. Warn for any submitted class_type that has a replacement. Best-effort:
    # if the server is unreachable or the endpoint doesn't exist, skip silently.
    node_replacements: dict[str, Any] | None = None
    if not errors:
        with contextlib.suppress(httpx.HTTPError, OSError):
            node_replacements = await client.get_node_replacements()

    # --- Loop structure (upstream Generic Loops, CORE-14) ---
    if not errors:
        starts, ends = _collect_loop_classes(workflow, object_info)
        if starts or ends:
            output_nodes = {
                node_id
                for node_id, node_data in workflow.items()
                if isinstance(node_data, dict)
                and (
                    (object_info or {}).get(node_data.get("class_type", ""), {}).get("output_node")
                    or node_data.get("class_type") in OUTPUT_NODE_TYPES
                )
            }
            loop_errors = validate_loop_structure(workflow, starts, ends, output_nodes)
            errors.extend(loop_errors)

    try:
        result = inspector.inspect(workflow, node_replacements=node_replacements)
        warnings.extend(result.warnings)
    except WorkflowBlockedError as e:
        errors.append(f"Security: {e}")
    except Exception:
        _logger.exception("Security inspection failed unexpectedly")
        errors.append("Security inspection failed due to an internal error")

    # --- Analysis ---
    analysis = analyze_workflow(workflow, object_info)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "node_count": analysis["node_count"],
        "pipeline": analysis["pipeline"],
    }
