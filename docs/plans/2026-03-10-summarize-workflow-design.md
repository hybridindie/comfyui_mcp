# `summarize_workflow` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `summarize_workflow` MCP tool that parses a ComfyUI workflow JSON and returns a human-readable summary enriched with display names from the ComfyUI API.

**Architecture:** New tool in `tools/generation.py` with two private helpers (`_analyze_workflow` for graph analysis, `_format_summary` for text output). Uses `graphlib.TopologicalSorter` for flow ordering. Calls `client.get_object_info()` best-effort for display names.

**Tech Stack:** Python 3.12 stdlib (`graphlib`, `json`), existing project infrastructure (FastMCP, httpx, pydantic)

---

### Task 1: Add `_analyze_workflow` helper with tests

**Files:**
- Modify: `src/comfyui_mcp/tools/generation.py:1-10` (add import for `graphlib`)
- Modify: `src/comfyui_mcp/tools/generation.py` (add `_analyze_workflow` after `_build_txt2img_workflow`)
- Test: `tests/test_tools_generation.py`

**Step 1: Write the failing test**

Add to `tests/test_tools_generation.py`:

```python
from comfyui_mcp.tools.generation import _analyze_workflow


class TestAnalyzeWorkflow:
    def test_analyzes_default_txt2img(self):
        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 0, "steps": 20, "cfg": 7.0,
                    "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                    "model": ["4", 0], "positive": ["6", 0],
                    "negative": ["7", 0], "latent_image": ["5", 0],
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
                "inputs": {"text": "a cat", "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "bad quality", "clip": ["4", 1]},
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
        result = _analyze_workflow(workflow, object_info=None)

        assert result["node_count"] == 7
        assert "CheckpointLoaderSimple" in result["class_types"]
        assert {"name": "v1-5-pruned-emaonly.safetensors", "type": "checkpoint"} in result["models"]
        assert result["parameters"]["steps"] == 20
        assert result["parameters"]["cfg"] == 7.0
        assert result["parameters"]["sampler"] == "euler"
        assert result["parameters"]["width"] == 512
        assert result["parameters"]["height"] == 512
        # Flow should be topologically sorted
        flow = [n["class_type"] for n in result["flow"]]
        assert flow.index("CheckpointLoaderSimple") < flow.index("KSampler")
        assert flow.index("KSampler") < flow.index("VAEDecode")
        assert flow.index("VAEDecode") < flow.index("SaveImage")

    def test_extracts_multiple_models(self):
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "dreamshaper_v8.safetensors"},
            },
            "2": {
                "class_type": "LoraLoader",
                "inputs": {
                    "lora_name": "add-detail.safetensors",
                    "model": ["1", 0], "clip": ["1", 1],
                },
            },
        }
        result = _analyze_workflow(workflow, object_info=None)
        names = [m["name"] for m in result["models"]]
        assert "dreamshaper_v8.safetensors" in names
        assert "add-detail.safetensors" in names

    def test_uses_display_names_from_object_info(self):
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"},
            },
        }
        object_info = {
            "CheckpointLoaderSimple": {
                "display_name": "Load Checkpoint",
            },
        }
        result = _analyze_workflow(workflow, object_info=object_info)
        assert result["flow"][0]["display_name"] == "Load Checkpoint"

    def test_handles_empty_workflow(self):
        result = _analyze_workflow({}, object_info=None)
        assert result["node_count"] == 0
        assert result["flow"] == []
        assert result["models"] == []

    def test_detects_pipeline_type_txt2img(self):
        workflow = {
            "1": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
            "2": {"class_type": "KSampler", "inputs": {"latent_image": ["1", 0]}},
            "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}},
        }
        result = _analyze_workflow(workflow, object_info=None)
        assert result["pipeline"] == "txt2img"

    def test_detects_pipeline_type_img2img(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
            "2": {"class_type": "KSampler", "inputs": {"latent_image": ["1", 0]}},
            "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}},
        }
        result = _analyze_workflow(workflow, object_info=None)
        assert result["pipeline"] == "img2img"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_generation.py::TestAnalyzeWorkflow -v`
Expected: FAIL with `ImportError: cannot import name '_analyze_workflow'`

**Step 3: Write the implementation**

Add to `src/comfyui_mcp/tools/generation.py`:

```python
import graphlib
```

Then add after `_build_txt2img_workflow`:

```python
# Node class_types that load models, mapped to their model input key and type label
_MODEL_LOADERS: dict[str, tuple[str, str]] = {
    "CheckpointLoaderSimple": ("ckpt_name", "checkpoint"),
    "CheckpointLoader": ("ckpt_name", "checkpoint"),
    "LoraLoader": ("lora_name", "lora"),
    "LoraLoaderModelOnly": ("lora_name", "lora"),
    "VAELoader": ("vae_name", "vae"),
    "UpscaleModelLoader": ("model_name", "upscale"),
    "ControlNetLoader": ("control_net_name", "controlnet"),
    "CLIPLoader": ("clip_name", "clip"),
    "UNETLoader": ("unet_name", "unet"),
}

_INPUT_NODE_TYPES = {"LoadImage", "LoadImageMask", "EmptyLatentImage"}
_OUTPUT_NODE_TYPES = {"SaveImage", "PreviewImage", "SaveAnimatedWEBP", "SaveAnimatedPNG"}
_SAMPLER_NODE_TYPES = {"KSampler", "KSamplerAdvanced", "SamplerCustom"}


def _analyze_workflow(
    workflow: dict[str, Any], object_info: dict[str, Any] | None
) -> dict[str, Any]:
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

    # Build graph edges: child -> set of parents (dependencies)
    deps: dict[str, set[str]] = {}
    node_info: dict[str, dict[str, Any]] = {}

    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        class_type = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})
        deps.setdefault(node_id, set())

        display_name = class_type
        if object_info and class_type in object_info:
            display_name = object_info[class_type].get("display_name", class_type)

        node_info[node_id] = {
            "node_id": node_id,
            "class_type": class_type,
            "display_name": display_name,
            "inputs": inputs,
        }

        for value in inputs.values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                parent_id = value[0]
                if parent_id in workflow:
                    deps[node_id].add(parent_id)
                    deps.setdefault(parent_id, set())

    # Topological sort
    sorter = graphlib.TopologicalSorter(deps)
    try:
        sorted_ids = list(sorter.static_order())
    except graphlib.CycleError:
        sorted_ids = list(node_info.keys())

    flow = [node_info[nid] for nid in sorted_ids if nid in node_info]
    class_types = [n["class_type"] for n in flow]

    # Extract models
    models: list[dict[str, str]] = []
    for node in flow:
        ct = node["class_type"]
        if ct in _MODEL_LOADERS:
            key, model_type = _MODEL_LOADERS[ct]
            name = node["inputs"].get(key, "")
            if name:
                models.append({"name": name, "type": model_type})

    # Extract parameters from sampler and latent nodes
    parameters: dict[str, Any] = {}
    for node in flow:
        ct = node["class_type"]
        if ct in _SAMPLER_NODE_TYPES:
            for k in ("steps", "cfg", "sampler_name", "scheduler", "denoise"):
                if k in node["inputs"]:
                    param_key = "sampler" if k == "sampler_name" else k
                    parameters[param_key] = node["inputs"][k]
        if ct == "EmptyLatentImage":
            for k in ("width", "height"):
                if k in node["inputs"]:
                    parameters[k] = node["inputs"][k]

    # Detect prompt/negative nodes
    prompt_nodes = []
    negative_nodes = []
    for node in flow:
        if node["class_type"] == "CLIPTextEncode":
            # Heuristic: if connected to a sampler's "negative" input, it's negative
            is_negative = False
            for other in flow:
                if other["class_type"] in _SAMPLER_NODE_TYPES:
                    neg_link = other["inputs"].get("negative")
                    if isinstance(neg_link, list) and neg_link[0] == node["node_id"]:
                        is_negative = True
                        break
            if is_negative:
                negative_nodes.append(node["node_id"])
            else:
                prompt_nodes.append(node["node_id"])

    # Pipeline type heuristic
    has_load_image = any(ct in _INPUT_NODE_TYPES - {"EmptyLatentImage"} for ct in class_types)
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_generation.py::TestAnalyzeWorkflow -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py
git commit -m "feat: add _analyze_workflow helper for workflow graph analysis"
```

---

### Task 2: Add `_format_summary` helper with tests

**Files:**
- Modify: `src/comfyui_mcp/tools/generation.py` (add `_format_summary` after `_analyze_workflow`)
- Test: `tests/test_tools_generation.py`

**Step 1: Write the failing test**

Add to `tests/test_tools_generation.py`:

```python
from comfyui_mcp.tools.generation import _format_summary


class TestFormatSummary:
    def test_formats_txt2img_summary(self):
        analysis = {
            "node_count": 7,
            "class_types": [
                "CheckpointLoaderSimple", "EmptyLatentImage",
                "CLIPTextEncode", "CLIPTextEncode",
                "KSampler", "VAEDecode", "SaveImage",
            ],
            "flow": [
                {"node_id": "4", "class_type": "CheckpointLoaderSimple", "display_name": "CheckpointLoaderSimple", "inputs": {}},
                {"node_id": "5", "class_type": "EmptyLatentImage", "display_name": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
                {"node_id": "6", "class_type": "CLIPTextEncode", "display_name": "CLIPTextEncode", "inputs": {}},
                {"node_id": "7", "class_type": "CLIPTextEncode", "display_name": "CLIPTextEncode", "inputs": {}},
                {"node_id": "3", "class_type": "KSampler", "display_name": "KSampler", "inputs": {"steps": 20, "cfg": 7.0}},
                {"node_id": "8", "class_type": "VAEDecode", "display_name": "VAEDecode", "inputs": {}},
                {"node_id": "9", "class_type": "SaveImage", "display_name": "SaveImage", "inputs": {}},
            ],
            "models": [{"name": "v1-5-pruned-emaonly.safetensors", "type": "checkpoint"}],
            "parameters": {"steps": 20, "cfg": 7.0, "sampler": "euler", "scheduler": "normal", "denoise": 1.0, "width": 512, "height": 512},
            "pipeline": "txt2img",
            "prompt_nodes": ["6"],
            "negative_nodes": ["7"],
        }
        result = _format_summary(analysis)
        assert "Workflow: 7 nodes" in result
        assert "Pipeline: txt2img" in result
        assert "v1-5-pruned-emaonly.safetensors (checkpoint)" in result
        assert "steps=20" in result
        assert "Prompt: node 6" in result
        assert "Negative: node 7" in result
        # Flow uses -> separator
        assert " -> " in result

    def test_formats_empty_workflow(self):
        analysis = {
            "node_count": 0,
            "class_types": [],
            "flow": [],
            "models": [],
            "parameters": {},
            "pipeline": "unknown",
            "prompt_nodes": [],
            "negative_nodes": [],
        }
        result = _format_summary(analysis)
        assert "Workflow: 0 nodes" in result

    def test_uses_display_names_in_flow(self):
        analysis = {
            "node_count": 1,
            "class_types": ["CheckpointLoaderSimple"],
            "flow": [
                {"node_id": "1", "class_type": "CheckpointLoaderSimple", "display_name": "Load Checkpoint", "inputs": {}},
            ],
            "models": [],
            "parameters": {},
            "pipeline": "unknown",
            "prompt_nodes": [],
            "negative_nodes": [],
        }
        result = _format_summary(analysis)
        assert "Load Checkpoint" in result

    def test_omits_prompt_line_when_no_prompt_nodes(self):
        analysis = {
            "node_count": 1,
            "class_types": ["SaveImage"],
            "flow": [{"node_id": "1", "class_type": "SaveImage", "display_name": "SaveImage", "inputs": {}}],
            "models": [],
            "parameters": {},
            "pipeline": "unknown",
            "prompt_nodes": [],
            "negative_nodes": [],
        }
        result = _format_summary(analysis)
        assert "Prompt:" not in result
        assert "Negative:" not in result

    def test_omits_parameters_line_when_no_params(self):
        analysis = {
            "node_count": 1,
            "class_types": ["SaveImage"],
            "flow": [{"node_id": "1", "class_type": "SaveImage", "display_name": "SaveImage", "inputs": {}}],
            "models": [],
            "parameters": {},
            "pipeline": "unknown",
            "prompt_nodes": [],
            "negative_nodes": [],
        }
        result = _format_summary(analysis)
        assert "Parameters:" not in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_generation.py::TestFormatSummary -v`
Expected: FAIL with `ImportError: cannot import name '_format_summary'`

**Step 3: Write the implementation**

Add to `src/comfyui_mcp/tools/generation.py` after `_analyze_workflow`:

```python
def _format_summary(analysis: dict[str, Any]) -> str:
    """Format an analysis dict into a human-readable summary."""
    lines: list[str] = []

    lines.append(f"Workflow: {analysis['node_count']} nodes")
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_generation.py::TestFormatSummary -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py
git commit -m "feat: add _format_summary helper for workflow text output"
```

---

### Task 3: Wire `summarize_workflow` tool and update `server.py`

**Files:**
- Modify: `src/comfyui_mcp/tools/generation.py:94-100` (update `register_generation_tools` signature, add tool)
- Modify: `src/comfyui_mcp/server.py:66-81` (pass read limiter)
- Test: `tests/test_tools_generation.py`

**Step 1: Write the failing test**

Add to `tests/test_tools_generation.py`:

```python
class TestSummarizeWorkflow:
    @respx.mock
    async def test_summarizes_txt2img_workflow(self, components):
        client, audit, limiter, inspector = components
        read_limiter = RateLimiter(max_per_minute=60)
        # Mock object_info endpoint
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={
                "KSampler": {"display_name": "KSampler"},
                "CheckpointLoaderSimple": {"display_name": "Load Checkpoint"},
            })
        )
        mcp_server = FastMCP("test")
        tools = register_generation_tools(
            mcp_server, client, audit, limiter, inspector, read_limiter=read_limiter,
        )
        workflow = {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
            "3": {"class_type": "KSampler", "inputs": {"steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "test", "images": ["8", 0]}},
        }
        result = await tools["summarize_workflow"](workflow=json.dumps(workflow))
        assert "7 nodes" in result
        assert "txt2img" in result
        assert "model.safetensors" in result
        assert "Load Checkpoint" in result

    @respx.mock
    async def test_fallback_when_object_info_fails(self, components):
        client, audit, limiter, inspector = components
        read_limiter = RateLimiter(max_per_minute=60)
        # Mock object_info to fail
        respx.get("http://test:8188/object_info").mock(side_effect=httpx.ConnectError("offline"))
        mcp_server = FastMCP("test")
        tools = register_generation_tools(
            mcp_server, client, audit, limiter, inspector, read_limiter=read_limiter,
        )
        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
        }
        result = await tools["summarize_workflow"](workflow=json.dumps(workflow))
        assert "1 nodes" in result
        assert "CheckpointLoaderSimple" in result

    async def test_rejects_invalid_json(self, components):
        client, audit, limiter, inspector = components
        read_limiter = RateLimiter(max_per_minute=60)
        mcp_server = FastMCP("test")
        tools = register_generation_tools(
            mcp_server, client, audit, limiter, inspector, read_limiter=read_limiter,
        )
        with pytest.raises(ValueError, match="Invalid JSON"):
            await tools["summarize_workflow"](workflow="not json")
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_generation.py::TestSummarizeWorkflow -v`
Expected: FAIL with `TypeError` (unexpected keyword argument `read_limiter`)

**Step 3: Update `register_generation_tools` signature and add tool**

In `src/comfyui_mcp/tools/generation.py`, update the function signature:

```python
def register_generation_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    inspector: WorkflowInspector,
    *,
    read_limiter: RateLimiter | None = None,
) -> dict[str, Any]:
```

Add the tool inside `register_generation_tools`, after `generate_image`:

```python
    @mcp.tool()
    async def summarize_workflow(workflow: str) -> str:
        """Summarize a ComfyUI workflow's structure, data flow, and key parameters.

        Parses the workflow graph, extracts models, parameters, and execution flow.
        Enriches with display names from the ComfyUI server when available.

        Args:
            workflow: JSON string of a ComfyUI workflow (API format).
                      Each key is a node ID, each value has 'class_type' and 'inputs'.
        """
        summary_limiter = read_limiter if read_limiter is not None else limiter
        summary_limiter.check("summarize_workflow")

        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e

        # Best-effort API enrichment
        object_info: dict[str, Any] | None = None
        try:
            object_info = await client.get_object_info()
        except Exception:
            pass

        analysis = _analyze_workflow(wf, object_info)
        audit.log(
            tool="summarize_workflow",
            action="summarized",
            extra={
                "node_count": analysis["node_count"],
                "pipeline": analysis["pipeline"],
            },
        )
        return _format_summary(analysis)

    tool_fns["summarize_workflow"] = summarize_workflow
```

**Step 4: Update `server.py` to pass `read_limiter`**

In `src/comfyui_mcp/server.py:80`, change:

```python
    register_generation_tools(server, client, audit, rate_limiters["generation"], inspector)
```

to:

```python
    register_generation_tools(
        server, client, audit, rate_limiters["generation"], inspector,
        read_limiter=rate_limiters["read"],
    )
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_generation.py -v`
Expected: ALL PASS

**Step 6: Run full test suite, lint, and type check**

```bash
uv run pytest -v
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/comfyui_mcp/
```

Expected: All pass

**Step 7: Commit**

```bash
git add src/comfyui_mcp/tools/generation.py src/comfyui_mcp/server.py tests/test_tools_generation.py
git commit -m "feat: add summarize_workflow tool with API-enriched display names

Closes #2"
```

---

### Task 4: Update README tools table

**Files:**
- Modify: `README.md` (add `summarize_workflow` to the tools table)

**Step 1: Add entry to tools table**

Add a row for `summarize_workflow` in the Tools section of `README.md`:

| `summarize_workflow` | Summarize a workflow's structure, data flow, models, and parameters |

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add summarize_workflow to README tools table"
```
