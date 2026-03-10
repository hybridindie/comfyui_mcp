# Workflow Composition Tools Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `create_workflow`, `modify_workflow`, and `validate_workflow` tools for programmatic ComfyUI workflow construction.

**Architecture:** New `src/comfyui_mcp/workflow/` package with three modules: `templates.py` (6 workflow templates), `operations.py` (batch graph operations), `validation.py` (structural + server + security checks). Thin tool registration layer in `src/comfyui_mcp/tools/workflow.py`. Workflow analysis utilities (`_analyze_workflow`, etc.) move from `generation.py` to `workflow/validation.py`.

**Tech Stack:** Python 3.12, FastMCP, httpx, graphlib, pydantic (for config), pytest + respx (testing)

**Spec:** `docs/superpowers/specs/2026-03-10-workflow-composition-design.md`

---

## Chunk 1: Operations Module

### Task 1: Create workflow package and operations module

**Files:**
- Create: `src/comfyui_mcp/workflow/__init__.py`
- Create: `src/comfyui_mcp/workflow/operations.py`
- Test: `tests/test_workflow_operations.py`

- [ ] **Step 1: Create the package init file**

```python
# src/comfyui_mcp/workflow/__init__.py
# (empty)
```

- [ ] **Step 2: Write failing tests for `add_node`**

Create `tests/test_workflow_operations.py`:

```python
"""Tests for workflow graph operations."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from comfyui_mcp.workflow.operations import apply_operations


def _simple_workflow() -> dict[str, Any]:
    """A minimal 2-node workflow for testing."""
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "model.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "a cat", "clip": ["1", 1]},
        },
    }


class TestAddNode:
    def test_add_node_with_explicit_id(self):
        wf = _simple_workflow()
        ops = [{"op": "add_node", "node_id": "10", "class_type": "VAEDecode", "inputs": {"samples": ["1", 0]}}]
        result = apply_operations(wf, ops)
        assert "10" in result
        assert result["10"]["class_type"] == "VAEDecode"
        assert result["10"]["inputs"]["samples"] == ["1", 0]

    def test_add_node_auto_generates_id(self):
        wf = _simple_workflow()
        ops = [{"op": "add_node", "class_type": "SaveImage"}]
        result = apply_operations(wf, ops)
        assert "3" in result
        assert result["3"]["class_type"] == "SaveImage"

    def test_add_node_default_empty_inputs(self):
        wf = _simple_workflow()
        ops = [{"op": "add_node", "class_type": "VAEDecode"}]
        result = apply_operations(wf, ops)
        assert result["3"]["inputs"] == {}

    def test_add_node_duplicate_id_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "add_node", "node_id": "1", "class_type": "SaveImage"}]
        with pytest.raises(ValueError, match="already exists"):
            apply_operations(wf, ops)

    def test_add_node_missing_class_type_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "add_node"}]
        with pytest.raises(ValueError, match="class_type"):
            apply_operations(wf, ops)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_operations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'comfyui_mcp.workflow'`

- [ ] **Step 4: Implement `apply_operations` with `add_node` support**

Create `src/comfyui_mcp/workflow/operations.py`:

```python
"""Batch operations for modifying ComfyUI workflows."""

from __future__ import annotations

import copy
from typing import Any


def _next_node_id(workflow: dict[str, Any]) -> str:
    """Generate the next integer node ID after the current max."""
    int_ids = []
    for k in workflow:
        try:
            int_ids.append(int(k))
        except ValueError:
            continue
    return str(max(int_ids, default=0) + 1)


def _apply_add_node(workflow: dict[str, Any], op: dict[str, Any]) -> None:
    """Add a node to the workflow."""
    class_type = op.get("class_type")
    if not class_type:
        raise ValueError("add_node requires 'class_type'")
    node_id = op.get("node_id") or _next_node_id(workflow)
    if node_id in workflow:
        raise ValueError(f"Node '{node_id}' already exists")
    inputs = op.get("inputs", {})
    workflow[node_id] = {"class_type": class_type, "inputs": inputs}


def apply_operations(
    workflow: dict[str, Any], operations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Apply a list of operations to a workflow. Returns a new workflow dict.

    Operations execute sequentially. If any fails, the original workflow
    is unchanged (atomic — operates on a deep copy).
    """
    result = copy.deepcopy(workflow)
    dispatch = {
        "add_node": _apply_add_node,
    }
    for i, op in enumerate(operations):
        op_type = op.get("op")
        handler = dispatch.get(op_type) if op_type else None
        if handler is None:
            raise ValueError(f"Operation {i}: unknown op '{op_type}'")
        handler(result, op)
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_operations.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Lint and type check**

Run: `uv run ruff check src/comfyui_mcp/workflow/ tests/test_workflow_operations.py && uv run ruff format src/comfyui_mcp/workflow/ tests/test_workflow_operations.py && uv run mypy src/comfyui_mcp/workflow/`

- [ ] **Step 7: Commit**

```bash
git add src/comfyui_mcp/workflow/ tests/test_workflow_operations.py
git commit -m "feat: add workflow operations module with add_node"
```

### Task 2: Add remove_node, set_input, connect, disconnect operations

**Files:**
- Modify: `src/comfyui_mcp/workflow/operations.py`
- Modify: `tests/test_workflow_operations.py`

- [ ] **Step 1: Write failing tests for remaining operations**

Append to `tests/test_workflow_operations.py`:

```python
class TestRemoveNode:
    def test_remove_existing_node(self):
        wf = _simple_workflow()
        ops = [{"op": "remove_node", "node_id": "2"}]
        result = apply_operations(wf, ops)
        assert "2" not in result
        assert "1" in result

    def test_remove_cleans_dangling_references(self):
        wf = _simple_workflow()
        # Node 2 references node 1. Add node 3 referencing node 2.
        wf["3"] = {"class_type": "KSampler", "inputs": {"positive": ["2", 0], "steps": 20}}
        ops = [{"op": "remove_node", "node_id": "2"}]
        result = apply_operations(wf, ops)
        assert "2" not in result
        # The reference to node 2 in node 3's inputs should be removed
        assert "positive" not in result["3"]["inputs"]
        # Scalar inputs are preserved
        assert result["3"]["inputs"]["steps"] == 20

    def test_remove_nonexistent_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "remove_node", "node_id": "99"}]
        with pytest.raises(ValueError, match="not found"):
            apply_operations(wf, ops)


class TestSetInput:
    def test_set_scalar_input(self):
        wf = _simple_workflow()
        ops = [{"op": "set_input", "node_id": "2", "input_name": "text", "value": "a dog"}]
        result = apply_operations(wf, ops)
        assert result["2"]["inputs"]["text"] == "a dog"

    def test_set_new_input(self):
        wf = _simple_workflow()
        ops = [{"op": "set_input", "node_id": "1", "input_name": "new_field", "value": 42}]
        result = apply_operations(wf, ops)
        assert result["1"]["inputs"]["new_field"] == 42

    def test_set_input_nonexistent_node_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "set_input", "node_id": "99", "input_name": "text", "value": "x"}]
        with pytest.raises(ValueError, match="not found"):
            apply_operations(wf, ops)


class TestConnect:
    def test_connect_nodes(self):
        wf = _simple_workflow()
        ops = [{"op": "connect", "from_node": "1", "from_output": 0, "to_node": "2", "to_input": "model"}]
        result = apply_operations(wf, ops)
        assert result["2"]["inputs"]["model"] == ["1", 0]

    def test_connect_nonexistent_from_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "connect", "from_node": "99", "from_output": 0, "to_node": "2", "to_input": "model"}]
        with pytest.raises(ValueError, match="not found"):
            apply_operations(wf, ops)

    def test_connect_nonexistent_to_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "connect", "from_node": "1", "from_output": 0, "to_node": "99", "to_input": "model"}]
        with pytest.raises(ValueError, match="not found"):
            apply_operations(wf, ops)


class TestDisconnect:
    def test_disconnect_input(self):
        wf = _simple_workflow()
        # Node 2 has "clip": ["1", 1] — a connection
        ops = [{"op": "disconnect", "node_id": "2", "input_name": "clip"}]
        result = apply_operations(wf, ops)
        assert "clip" not in result["2"]["inputs"]

    def test_disconnect_nonexistent_node_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "disconnect", "node_id": "99", "input_name": "clip"}]
        with pytest.raises(ValueError, match="not found"):
            apply_operations(wf, ops)

    def test_disconnect_nonexistent_input_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "disconnect", "node_id": "2", "input_name": "nonexistent"}]
        with pytest.raises(ValueError, match="no input"):
            apply_operations(wf, ops)
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `uv run pytest tests/test_workflow_operations.py -v`
Expected: New tests FAIL, existing tests PASS

- [ ] **Step 3: Implement remaining operations**

Add to `src/comfyui_mcp/workflow/operations.py`:

```python
def _apply_remove_node(workflow: dict[str, Any], op: dict[str, Any]) -> None:
    """Remove a node and clean up dangling references."""
    node_id = op.get("node_id")
    if node_id not in workflow:
        raise ValueError(f"Node '{node_id}' not found")
    del workflow[node_id]
    # Clean up references to the removed node in other nodes' inputs
    for node_data in workflow.values():
        inputs = node_data.get("inputs", {})
        to_remove = []
        for key, value in inputs.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                if value[0] == node_id:
                    to_remove.append(key)
        for key in to_remove:
            del inputs[key]


def _apply_set_input(workflow: dict[str, Any], op: dict[str, Any]) -> None:
    """Set an input value on a node."""
    node_id = op.get("node_id")
    if node_id not in workflow:
        raise ValueError(f"Node '{node_id}' not found")
    input_name = op.get("input_name")
    value = op.get("value")
    workflow[node_id]["inputs"][input_name] = value


def _apply_connect(workflow: dict[str, Any], op: dict[str, Any]) -> None:
    """Connect one node's output to another node's input."""
    from_node = op.get("from_node")
    to_node = op.get("to_node")
    if from_node not in workflow:
        raise ValueError(f"Source node '{from_node}' not found")
    if to_node not in workflow:
        raise ValueError(f"Target node '{to_node}' not found")
    from_output = op.get("from_output", 0)
    to_input = op.get("to_input")
    workflow[to_node]["inputs"][to_input] = [from_node, from_output]


def _apply_disconnect(workflow: dict[str, Any], op: dict[str, Any]) -> None:
    """Clear a connection on a node's input."""
    node_id = op.get("node_id")
    if node_id not in workflow:
        raise ValueError(f"Node '{node_id}' not found")
    input_name = op.get("input_name")
    inputs = workflow[node_id]["inputs"]
    if input_name not in inputs:
        raise ValueError(f"Node '{node_id}' has no input '{input_name}'")
    del inputs[input_name]
```

Update the `dispatch` dict in `apply_operations`:

```python
    dispatch = {
        "add_node": _apply_add_node,
        "remove_node": _apply_remove_node,
        "set_input": _apply_set_input,
        "connect": _apply_connect,
        "disconnect": _apply_disconnect,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_operations.py -v`
Expected: All tests PASS

- [ ] **Step 5: Lint and type check**

Run: `uv run ruff check src/comfyui_mcp/workflow/ tests/test_workflow_operations.py && uv run ruff format src/comfyui_mcp/workflow/ tests/test_workflow_operations.py && uv run mypy src/comfyui_mcp/workflow/`

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/workflow/operations.py tests/test_workflow_operations.py
git commit -m "feat: add remove_node, set_input, connect, disconnect operations"
```

### Task 3: Add batch ordering and atomicity tests

**Files:**
- Modify: `tests/test_workflow_operations.py`

- [ ] **Step 1: Write tests for batch behavior**

Append to `tests/test_workflow_operations.py`:

```python
class TestBatchBehavior:
    def test_operations_apply_sequentially(self):
        """Adding a node then connecting to it should work."""
        wf = _simple_workflow()
        ops = [
            {"op": "add_node", "node_id": "3", "class_type": "VAEDecode"},
            {"op": "connect", "from_node": "1", "from_output": 2, "to_node": "3", "to_input": "vae"},
        ]
        result = apply_operations(wf, ops)
        assert result["3"]["inputs"]["vae"] == ["1", 2]

    def test_atomic_failure_preserves_original(self):
        """If op 2 fails, op 1 should not be applied to the original."""
        wf = _simple_workflow()
        original = copy.deepcopy(wf)
        ops = [
            {"op": "add_node", "node_id": "3", "class_type": "VAEDecode"},
            {"op": "connect", "from_node": "99", "from_output": 0, "to_node": "3", "to_input": "x"},
        ]
        with pytest.raises(ValueError):
            apply_operations(wf, ops)
        # Original workflow should be unchanged
        assert wf == original

    def test_unknown_op_raises(self):
        wf = _simple_workflow()
        ops = [{"op": "explode"}]
        with pytest.raises(ValueError, match="unknown op"):
            apply_operations(wf, ops)

    def test_empty_operations_returns_copy(self):
        wf = _simple_workflow()
        result = apply_operations(wf, [])
        assert result == wf
        assert result is not wf
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_operations.py -v`
Expected: All tests PASS (these test already-implemented behavior)

- [ ] **Step 3: Commit**

```bash
git add tests/test_workflow_operations.py
git commit -m "test: add batch ordering and atomicity tests for operations"
```

---

## Chunk 2: Templates Module

### Task 4: Create txt2img and img2img templates

**Files:**
- Create: `src/comfyui_mcp/workflow/templates.py`
- Create: `tests/test_workflow_templates.py`

- [ ] **Step 1: Write failing tests for txt2img template**

Create `tests/test_workflow_templates.py`:

```python
"""Tests for workflow templates."""

from __future__ import annotations

import json
from typing import Any

import pytest

from comfyui_mcp.workflow.templates import create_from_template, TEMPLATES


def _get_nodes_by_type(wf: dict[str, Any], class_type: str) -> list[dict[str, Any]]:
    """Find all nodes of a given class_type in a workflow."""
    return [v for v in wf.values() if v.get("class_type") == class_type]


def _has_connection_to(wf: dict[str, Any], target_node_id: str, input_name: str) -> bool:
    """Check if a node's input is a connection (list reference)."""
    node = wf.get(target_node_id)
    if not node:
        return False
    value = node.get("inputs", {}).get(input_name)
    return isinstance(value, list) and len(value) == 2


class TestTxt2ImgTemplate:
    def test_returns_valid_workflow(self):
        wf = create_from_template("txt2img")
        assert isinstance(wf, dict)
        assert len(wf) >= 7
        # Must have all core node types
        class_types = {v["class_type"] for v in wf.values()}
        assert "CheckpointLoaderSimple" in class_types
        assert "EmptyLatentImage" in class_types
        assert "KSampler" in class_types
        assert "CLIPTextEncode" in class_types
        assert "VAEDecode" in class_types
        assert "SaveImage" in class_types

    def test_params_override_defaults(self):
        wf = create_from_template("txt2img", {"prompt": "a dog", "width": 768, "height": 1024, "steps": 30})
        latent_nodes = _get_nodes_by_type(wf, "EmptyLatentImage")
        assert latent_nodes[0]["inputs"]["width"] == 768
        assert latent_nodes[0]["inputs"]["height"] == 1024
        sampler_nodes = _get_nodes_by_type(wf, "KSampler")
        assert sampler_nodes[0]["inputs"]["steps"] == 30
        # Check prompt was set on a CLIPTextEncode node
        clip_nodes = _get_nodes_by_type(wf, "CLIPTextEncode")
        texts = [n["inputs"].get("text") for n in clip_nodes]
        assert "a dog" in texts

    def test_model_override(self):
        wf = create_from_template("txt2img", {"model": "dreamshaper_v8.safetensors"})
        loader = _get_nodes_by_type(wf, "CheckpointLoaderSimple")
        assert loader[0]["inputs"]["ckpt_name"] == "dreamshaper_v8.safetensors"

    def test_unknown_params_ignored(self):
        wf = create_from_template("txt2img", {"nonexistent_param": 999})
        assert isinstance(wf, dict)


class TestImg2ImgTemplate:
    def test_returns_valid_workflow(self):
        wf = create_from_template("img2img")
        class_types = {v["class_type"] for v in wf.values()}
        assert "CheckpointLoaderSimple" in class_types
        assert "LoadImage" in class_types
        assert "KSampler" in class_types
        assert "VAEEncode" in class_types
        assert "VAEDecode" in class_types
        assert "SaveImage" in class_types

    def test_denoise_param(self):
        wf = create_from_template("img2img", {"denoise": 0.6})
        sampler = _get_nodes_by_type(wf, "KSampler")
        assert sampler[0]["inputs"]["denoise"] == 0.6


class TestInvalidTemplate:
    def test_invalid_template_raises(self):
        with pytest.raises(ValueError, match="Unknown template"):
            create_from_template("nonexistent")

    def test_templates_registry_has_all(self):
        expected = {"txt2img", "img2img", "upscale", "inpaint", "txt2vid_animatediff", "txt2vid_wan"}
        assert set(TEMPLATES.keys()) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_templates.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement templates module with txt2img and img2img**

Create `src/comfyui_mcp/workflow/templates.py`:

```python
"""Workflow templates for common ComfyUI pipelines."""

from __future__ import annotations

import copy
from typing import Any

# --- txt2img template ---
_TXT2IMG: dict[str, dict[str, Any]] = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "2": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "4": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "bad quality, blurry", "clip": ["1", 1]},
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["1", 0],
            "positive": ["3", 0],
            "negative": ["4", 0],
            "latent_image": ["2", 0],
        },
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "comfyui-mcp", "images": ["6", 0]},
    },
}

# --- img2img template ---
_IMG2IMG: dict[str, dict[str, Any]] = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "2": {
        "class_type": "LoadImage",
        "inputs": {"image": "input.png"},
    },
    "3": {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["2", 0], "vae": ["1", 2]},
    },
    "4": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "5": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "bad quality, blurry", "clip": ["1", 1]},
    },
    "6": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 0.75,
            "model": ["1", 0],
            "positive": ["4", 0],
            "negative": ["5", 0],
            "latent_image": ["3", 0],
        },
    },
    "7": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["6", 0], "vae": ["1", 2]},
    },
    "8": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "comfyui-mcp", "images": ["7", 0]},
    },
}

# --- upscale template ---
_UPSCALE: dict[str, dict[str, Any]] = {
    "1": {
        "class_type": "LoadImage",
        "inputs": {"image": "input.png"},
    },
    "2": {
        "class_type": "UpscaleModelLoader",
        "inputs": {"model_name": "RealESRGAN_x4plus.pth"},
    },
    "3": {
        "class_type": "ImageUpscaleWithModel",
        "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]},
    },
    "4": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "comfyui-mcp-upscale", "images": ["3", 0]},
    },
}

# --- inpaint template ---
_INPAINT: dict[str, dict[str, Any]] = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "2": {
        "class_type": "LoadImage",
        "inputs": {"image": "input.png"},
    },
    "3": {
        "class_type": "LoadImageMask",
        "inputs": {"image": "mask.png", "channel": "alpha"},
    },
    "4": {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["2", 0], "vae": ["1", 2]},
    },
    "5": {
        "class_type": "SetLatentNoiseMask",
        "inputs": {"samples": ["4", 0], "mask": ["3", 0]},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "bad quality, blurry", "clip": ["1", 1]},
    },
    "8": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 0.8,
            "model": ["1", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "9": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["8", 0], "vae": ["1", 2]},
    },
    "10": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "comfyui-mcp-inpaint", "images": ["9", 0]},
    },
}

# --- txt2vid AnimateDiff template ---
_TXT2VID_ANIMATEDIFF: dict[str, dict[str, Any]] = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "2": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 16},
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "4": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "bad quality, blurry", "clip": ["1", 1]},
    },
    "5": {
        "class_type": "ADE_AnimateDiffLoaderWithContext",
        "inputs": {
            "model_name": "mm_sd_v15_v2.ckpt",
            "beta_schedule": "sqrt_linear (AnimateDiff)",
            "model": ["1", 0],
        },
    },
    "6": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["5", 0],
            "positive": ["3", 0],
            "negative": ["4", 0],
            "latent_image": ["2", 0],
        },
    },
    "7": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["6", 0], "vae": ["1", 2]},
    },
    "8": {
        "class_type": "SaveAnimatedWEBP",
        "inputs": {
            "filename_prefix": "comfyui-mcp-anim",
            "fps": 8.0,
            "lossless": False,
            "quality": 85,
            "method": "default",
            "images": ["7", 0],
        },
    },
}

# --- txt2vid Wan template ---
_TXT2VID_WAN: dict[str, dict[str, Any]] = {
    "1": {
        "class_type": "DownloadAndLoadWanModel",
        "inputs": {
            "model": "Wan2.1-T2V-14B-bf16",
        },
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "bad quality, blurry", "clip": ["1", 1]},
    },
    "4": {
        "class_type": "WanTextToVideo",
        "inputs": {
            "width": 832,
            "height": 480,
            "num_frames": 81,
            "steps": 30,
            "cfg": 5.0,
            "seed": 0,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
        },
    },
    "5": {
        "class_type": "SaveAnimatedWEBP",
        "inputs": {
            "filename_prefix": "comfyui-mcp-wan",
            "fps": 16.0,
            "lossless": False,
            "quality": 85,
            "method": "default",
            "images": ["4", 0],
        },
    },
}


# --- Param application ---

# Maps param name -> list of (class_type, input_key) targets
_PARAM_MAP: dict[str, list[tuple[str, str]]] = {
    "prompt": [("CLIPTextEncode", "text")],  # Applied only to the first (positive) CLIPTextEncode
    "negative_prompt": [],  # Special handling: applied to second CLIPTextEncode
    "width": [("EmptyLatentImage", "width"), ("WanTextToVideo", "width")],
    "height": [("EmptyLatentImage", "height"), ("WanTextToVideo", "height")],
    "steps": [("KSampler", "steps"), ("WanTextToVideo", "steps")],
    "cfg": [("KSampler", "cfg"), ("WanTextToVideo", "cfg")],
    "denoise": [("KSampler", "denoise")],
    "model": [("CheckpointLoaderSimple", "ckpt_name")],
    "model_name": [("UpscaleModelLoader", "model_name")],
    "motion_module": [("ADE_AnimateDiffLoaderWithContext", "model_name")],
    "frames": [("EmptyLatentImage", "batch_size"), ("WanTextToVideo", "num_frames")],
    "seed": [("KSampler", "seed"), ("WanTextToVideo", "seed")],
    "sampler_name": [("KSampler", "sampler_name")],
    "scheduler": [("KSampler", "scheduler")],
    "image": [("LoadImage", "image")],
    "mask": [("LoadImageMask", "image")],
    "fps": [("SaveAnimatedWEBP", "fps")],
}


def _apply_params(wf: dict[str, Any], params: dict[str, Any]) -> None:
    """Apply parameter overrides to a workflow in-place."""
    # Build a lookup: class_type -> list of (node_id, node_data)
    by_type: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for nid, ndata in wf.items():
        ct = ndata.get("class_type", "")
        by_type.setdefault(ct, []).append((nid, ndata))

    for param_name, value in params.items():
        if param_name == "negative_prompt":
            # Apply to the second CLIPTextEncode (negative)
            clip_nodes = by_type.get("CLIPTextEncode", [])
            if len(clip_nodes) >= 2:
                clip_nodes[1][1]["inputs"]["text"] = value
            continue

        if param_name == "prompt":
            # Apply to the first CLIPTextEncode (positive)
            clip_nodes = by_type.get("CLIPTextEncode", [])
            if clip_nodes:
                clip_nodes[0][1]["inputs"]["text"] = value
            continue

        targets = _PARAM_MAP.get(param_name, [])
        for class_type, input_key in targets:
            for _, ndata in by_type.get(class_type, []):
                if input_key in ndata["inputs"]:
                    ndata["inputs"][input_key] = value


TEMPLATES: dict[str, dict[str, dict[str, Any]]] = {
    "txt2img": _TXT2IMG,
    "img2img": _IMG2IMG,
    "upscale": _UPSCALE,
    "inpaint": _INPAINT,
    "txt2vid_animatediff": _TXT2VID_ANIMATEDIFF,
    "txt2vid_wan": _TXT2VID_WAN,
}


def create_from_template(
    template: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Create a workflow from a named template with optional param overrides."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template '{template}'. Available: {', '.join(sorted(TEMPLATES))}")
    wf = copy.deepcopy(TEMPLATES[template])
    if params:
        _apply_params(wf, params)
    return wf
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_templates.py -v`
Expected: All tests PASS

- [ ] **Step 5: Lint and type check**

Run: `uv run ruff check src/comfyui_mcp/workflow/templates.py tests/test_workflow_templates.py && uv run ruff format src/comfyui_mcp/workflow/templates.py tests/test_workflow_templates.py && uv run mypy src/comfyui_mcp/workflow/`

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/workflow/templates.py tests/test_workflow_templates.py
git commit -m "feat: add workflow templates for all 6 pipeline types"
```

### Task 5: Add template-specific tests for remaining templates

**Files:**
- Modify: `tests/test_workflow_templates.py`

- [ ] **Step 1: Write tests for upscale, inpaint, and video templates**

Append to `tests/test_workflow_templates.py`:

```python
class TestUpscaleTemplate:
    def test_returns_valid_workflow(self):
        wf = create_from_template("upscale")
        class_types = {v["class_type"] for v in wf.values()}
        assert "LoadImage" in class_types
        assert "UpscaleModelLoader" in class_types
        assert "ImageUpscaleWithModel" in class_types
        assert "SaveImage" in class_types

    def test_model_name_override(self):
        wf = create_from_template("upscale", {"model_name": "4x_NMKD-Superscale-SP_178000_G.pth"})
        loader = _get_nodes_by_type(wf, "UpscaleModelLoader")
        assert loader[0]["inputs"]["model_name"] == "4x_NMKD-Superscale-SP_178000_G.pth"


class TestInpaintTemplate:
    def test_returns_valid_workflow(self):
        wf = create_from_template("inpaint")
        class_types = {v["class_type"] for v in wf.values()}
        assert "LoadImage" in class_types
        assert "LoadImageMask" in class_types
        assert "SetLatentNoiseMask" in class_types
        assert "KSampler" in class_types
        assert "VAEDecode" in class_types


class TestTxt2VidAnimateDiffTemplate:
    def test_returns_valid_workflow(self):
        wf = create_from_template("txt2vid_animatediff")
        class_types = {v["class_type"] for v in wf.values()}
        assert "ADE_AnimateDiffLoaderWithContext" in class_types
        assert "KSampler" in class_types
        assert "SaveAnimatedWEBP" in class_types

    def test_frames_param(self):
        wf = create_from_template("txt2vid_animatediff", {"frames": 32})
        latent = _get_nodes_by_type(wf, "EmptyLatentImage")
        assert latent[0]["inputs"]["batch_size"] == 32

    def test_motion_module_param(self):
        wf = create_from_template("txt2vid_animatediff", {"motion_module": "mm_sd15_v3.ckpt"})
        ad = _get_nodes_by_type(wf, "ADE_AnimateDiffLoaderWithContext")
        assert ad[0]["inputs"]["model_name"] == "mm_sd15_v3.ckpt"


class TestTxt2VidWanTemplate:
    def test_returns_valid_workflow(self):
        wf = create_from_template("txt2vid_wan")
        class_types = {v["class_type"] for v in wf.values()}
        assert "DownloadAndLoadWanModel" in class_types
        assert "WanTextToVideo" in class_types
        assert "SaveAnimatedWEBP" in class_types

    def test_dimensions_param(self):
        wf = create_from_template("txt2vid_wan", {"width": 1280, "height": 720})
        wan = _get_nodes_by_type(wf, "WanTextToVideo")
        assert wan[0]["inputs"]["width"] == 1280
        assert wan[0]["inputs"]["height"] == 720

    def test_frames_param(self):
        wf = create_from_template("txt2vid_wan", {"frames": 49})
        wan = _get_nodes_by_type(wf, "WanTextToVideo")
        assert wan[0]["inputs"]["num_frames"] == 49
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_templates.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_workflow_templates.py
git commit -m "test: add template tests for upscale, inpaint, and video pipelines"
```

---

## Chunk 3: Validation Module

### Task 6: Move analysis utilities from generation.py to workflow/validation.py

**Files:**
- Create: `src/comfyui_mcp/workflow/validation.py`
- Modify: `src/comfyui_mcp/tools/generation.py:97-249`
- Modify: `tests/test_tools_generation.py:14-18` (update imports)

- [ ] **Step 1: Create validation.py with moved code**

Create `src/comfyui_mcp/workflow/validation.py` containing:
- `_MODEL_LOADERS` (from `generation.py:98-108`)
- `_INPUT_NODE_TYPES` (from `generation.py:110`)
- `_SAMPLER_NODE_TYPES` (from `generation.py:111`)
- `WorkflowAnalysis` (from `generation.py:114-124`)
- `_analyze_workflow()` (from `generation.py:127-249`)

```python
"""Workflow validation: structural checks, server checks, and security inspection."""

from __future__ import annotations

import graphlib
from typing import Any, TypedDict

# Node class_types that load models, mapped to their model input key and type label
MODEL_LOADERS: dict[str, tuple[str, str]] = {
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

INPUT_NODE_TYPES = {"LoadImage", "LoadImageMask", "EmptyLatentImage"}
SAMPLER_NODE_TYPES = {"KSampler", "KSamplerAdvanced", "SamplerCustom"}


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


def analyze_workflow(
    workflow: dict[str, Any], object_info: dict[str, Any] | None = None
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

    # Build graph edges: child -> set of parents (dependencies)
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
        if ct in MODEL_LOADERS:
            key, model_type = MODEL_LOADERS[ct]
            name = node["inputs"].get(key, "")
            if name:
                models.append({"name": name, "type": model_type})

    # Extract parameters from sampler and latent nodes
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

    # Detect prompt/negative nodes
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

    # Pipeline type heuristic
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
```

Note: The public names drop the underscore prefix (`MODEL_LOADERS`, `SAMPLER_NODE_TYPES`, `INPUT_NODE_TYPES`, `analyze_workflow`) since they are now part of a module's public API.

- [ ] **Step 2: Update generation.py to import from workflow.validation**

In `src/comfyui_mcp/tools/generation.py`, remove lines 97-249 (the moved code) and replace with imports:

```python
from comfyui_mcp.workflow.validation import (
    MODEL_LOADERS as _MODEL_LOADERS,
    SAMPLER_NODE_TYPES as _SAMPLER_NODE_TYPES,
    WorkflowAnalysis,
    analyze_workflow as _analyze_workflow,
)
```

Keep `_format_summary` in `generation.py` — it uses `_SAMPLER_NODE_TYPES` (now imported).

Update `_format_summary` to reference the imported names. Since we alias them with underscores to preserve existing usage, no other changes needed in `_format_summary`.

Update the `summarize_workflow` tool to call `_analyze_workflow(wf, object_info)` (same as before, since we aliased the import).

- [ ] **Step 3: Update test imports**

In `tests/test_tools_generation.py:14-18`, update:

```python
from comfyui_mcp.workflow.validation import analyze_workflow as _analyze_workflow
from comfyui_mcp.tools.generation import (
    _format_summary,
    register_generation_tools,
)
```

Update any test references from `_analyze_workflow` to match the new import.

- [ ] **Step 4: Run full test suite to verify nothing broke**

Run: `uv run pytest -v`
Expected: All existing tests PASS

- [ ] **Step 5: Lint and type check**

Run: `uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/comfyui_mcp/`

- [ ] **Step 6: Commit**

```bash
git add src/comfyui_mcp/workflow/validation.py src/comfyui_mcp/tools/generation.py tests/test_tools_generation.py
git commit -m "refactor: move workflow analysis utilities to workflow.validation"
```

### Task 7: Add structural and server validation

**Files:**
- Modify: `src/comfyui_mcp/workflow/validation.py`
- Create: `tests/test_workflow_validation.py`

- [ ] **Step 1: Write failing tests for structural validation**

Create `tests/test_workflow_validation.py`:

```python
"""Tests for workflow validation."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.workflow.validation import validate_workflow


def _valid_workflow() -> dict[str, Any]:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "model.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "a cat", "clip": ["1", 1]},
        },
    }


@pytest.fixture
def client():
    return ComfyUIClient(base_url="http://test:8188")


@pytest.fixture
def inspector():
    return WorkflowInspector(mode="audit", dangerous_nodes=["EvalNode"], allowed_nodes=[])


class TestStructuralValidation:
    @respx.mock
    async def test_valid_workflow_passes(self, client, inspector):
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={
                "CheckpointLoaderSimple": {"display_name": "Load Checkpoint", "input": {"required": {"ckpt_name": [["model.safetensors"]]}}},
                "CLIPTextEncode": {"display_name": "CLIP Text Encode", "input": {"required": {"text": ["STRING"], "clip": ["CLIP"]}}},
            })
        )
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["model.safetensors"])
        )
        result = await validate_workflow(_valid_workflow(), client, inspector)
        assert result["valid"] is True
        assert result["errors"] == []

    async def test_missing_class_type_is_error(self, client, inspector):
        wf = {"1": {"inputs": {"x": 1}}}
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("class_type" in e for e in result["errors"])

    async def test_broken_connection_is_error(self, client, inspector):
        wf = {
            "1": {
                "class_type": "KSampler",
                "inputs": {"model": ["99", 0]},
            },
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("99" in e for e in result["errors"])

    async def test_cycle_is_error(self, client, inspector):
        wf = {
            "1": {"class_type": "A", "inputs": {"x": ["2", 0]}},
            "2": {"class_type": "B", "inputs": {"x": ["1", 0]}},
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("cycle" in e.lower() for e in result["errors"])


class TestServerValidation:
    @respx.mock
    async def test_missing_node_type_is_error(self, client, inspector):
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={
                "CheckpointLoaderSimple": {"display_name": "Load Checkpoint", "input": {"required": {}}},
            })
        )
        wf = _valid_workflow()  # Has CLIPTextEncode which is NOT in object_info
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("CLIPTextEncode" in e and "not installed" in e for e in result["errors"])

    @respx.mock
    async def test_missing_model_is_warning(self, client, inspector):
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={
                "CheckpointLoaderSimple": {"display_name": "Load Checkpoint", "input": {"required": {"ckpt_name": [["other.safetensors"]]}}},
                "CLIPTextEncode": {"display_name": "CLIP Text Encode", "input": {"required": {"text": ["STRING"], "clip": ["CLIP"]}}},
            })
        )
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["other.safetensors"])
        )
        wf = _valid_workflow()  # Has model.safetensors which is NOT in models list
        result = await validate_workflow(wf, client, inspector)
        assert any("model.safetensors" in w for w in result["warnings"])

    @respx.mock
    async def test_server_unreachable_adds_warning(self, client, inspector):
        respx.get("http://test:8188/object_info").mock(side_effect=httpx.ConnectError("offline"))
        wf = _valid_workflow()
        result = await validate_workflow(wf, client, inspector)
        # Should still return structural results, with a warning about server
        assert any("server" in w.lower() for w in result["warnings"])
        assert result["node_count"] == 2


class TestSecurityValidation:
    @respx.mock
    async def test_dangerous_node_adds_warning(self, client, inspector):
        respx.get("http://test:8188/object_info").mock(side_effect=httpx.ConnectError("offline"))
        wf = {"1": {"class_type": "EvalNode", "inputs": {}}}
        result = await validate_workflow(wf, client, inspector)
        assert any("Dangerous" in w for w in result["warnings"])

    @respx.mock
    async def test_enforce_mode_blocks(self, client):
        respx.get("http://test:8188/object_info").mock(side_effect=httpx.ConnectError("offline"))
        enforce_inspector = WorkflowInspector(
            mode="enforce",
            dangerous_nodes=[],
            allowed_nodes=["CheckpointLoaderSimple"],
        )
        wf = _valid_workflow()  # Has CLIPTextEncode which is not allowed
        result = await validate_workflow(wf, client, enforce_inspector)
        assert result["valid"] is False
        assert any("blocked" in e.lower() for e in result["errors"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_validation.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_workflow'`

- [ ] **Step 3: Implement validate_workflow**

Add to `src/comfyui_mcp/workflow/validation.py`:

```python
import contextlib
import httpx

from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowBlockedError, WorkflowInspector


async def validate_workflow(
    workflow: dict[str, Any],
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
        inputs = node_data.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for input_name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                ref_id = value[0]
                if ref_id not in workflow:
                    errors.append(
                        f"Node '{node_id}' input '{input_name}': references non-existent node '{ref_id}'"
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
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                if value[0] in workflow:
                    deps[node_id].add(value[0])
                    deps.setdefault(value[0], set())

    sorter = graphlib.TopologicalSorter(deps)
    try:
        sorter.static_order()
    except graphlib.CycleError as e:
        errors.append(f"Workflow contains a cycle: {e}")

    # --- Server checks (best-effort) ---
    object_info: dict[str, Any] | None = None
    with contextlib.suppress(httpx.HTTPError, OSError):
        object_info = await client.get_object_info()

    if object_info is None:
        warnings.append("ComfyUI server unreachable — server validation skipped")
    else:
        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue
            ct = node_data.get("class_type", "")
            if ct and ct not in object_info:
                errors.append(f"Node '{node_id}': class_type '{ct}' not installed on server")

        # Check models exist
        for node_id, node_data in workflow.items():
            if not isinstance(node_data, dict):
                continue
            ct = node_data.get("class_type", "")
            if ct in MODEL_LOADERS:
                input_key, model_type = MODEL_LOADERS[ct]
                model_name = node_data.get("inputs", {}).get(input_key, "")
                if model_name:
                    # Map model_type to folder name
                    folder_map = {
                        "checkpoint": "checkpoints",
                        "lora": "loras",
                        "vae": "vae",
                        "upscale": "upscale_models",
                        "controlnet": "controlnet",
                        "clip": "clip",
                        "unet": "unet",
                    }
                    folder = folder_map.get(model_type, model_type)
                    available: list[str] = []
                    with contextlib.suppress(httpx.HTTPError, OSError):
                        available = await client.get_models(folder)
                    if available and model_name not in available:
                        warnings.append(
                            f"Node '{node_id}': {model_type} model '{model_name}' not found in '{folder}'"
                        )

    # --- Security inspection ---
    try:
        result = inspector.inspect(workflow)
        warnings.extend(result.warnings)
    except WorkflowBlockedError as e:
        errors.append(f"Security: workflow blocked — {e}")

    # --- Analysis ---
    analysis = analyze_workflow(workflow, object_info)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "node_count": analysis["node_count"],
        "pipeline": analysis["pipeline"],
    }
```

Add these imports at the top of `validation.py`:

```python
import contextlib
import httpx
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowBlockedError, WorkflowInspector
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_validation.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 6: Lint and type check**

Run: `uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/comfyui_mcp/`

- [ ] **Step 7: Commit**

```bash
git add src/comfyui_mcp/workflow/validation.py tests/test_workflow_validation.py
git commit -m "feat: add validate_workflow with structural, server, and security checks"
```

---

## Chunk 4: Tool Registration and Wiring

### Task 8: Create tools/workflow.py and wire into server.py

**Files:**
- Create: `src/comfyui_mcp/tools/workflow.py`
- Modify: `src/comfyui_mcp/server.py:16-21,66-87`
- Create: `tests/test_tools_workflow.py`

- [ ] **Step 1: Write failing tests for tool registration**

Create `tests/test_tools_workflow.py`:

```python
"""Tests for workflow composition MCP tools."""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
import pytest
import respx
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.tools.workflow import register_workflow_tools


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    inspector = WorkflowInspector(mode="audit", dangerous_nodes=["EvalNode"], allowed_nodes=[])
    return client, audit, limiter, inspector


class TestCreateWorkflow:
    async def test_creates_txt2img(self, components):
        client, audit, limiter, inspector = components
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        result = await tools["create_workflow"](template="txt2img")
        wf = json.loads(result)
        class_types = {v["class_type"] for v in wf.values()}
        assert "KSampler" in class_types
        assert "CheckpointLoaderSimple" in class_types

    async def test_creates_with_params(self, components):
        client, audit, limiter, inspector = components
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        params = json.dumps({"prompt": "a dog", "steps": 30})
        result = await tools["create_workflow"](template="txt2img", params=params)
        wf = json.loads(result)
        # Verify params applied
        sampler = [v for v in wf.values() if v["class_type"] == "KSampler"][0]
        assert sampler["inputs"]["steps"] == 30

    async def test_invalid_template_raises(self, components):
        client, audit, limiter, inspector = components
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        with pytest.raises(ValueError, match="Unknown template"):
            await tools["create_workflow"](template="nonexistent")

    async def test_audit_log_written(self, components):
        client, audit, limiter, inspector = components
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        await tools["create_workflow"](template="txt2img")
        log_lines = audit._audit_file.read_text().strip().split("\n")
        entries = [json.loads(line) for line in log_lines]
        assert any(e["tool"] == "create_workflow" for e in entries)


class TestModifyWorkflow:
    async def test_adds_node(self, components):
        client, audit, limiter, inspector = components
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        wf = json.dumps({"1": {"class_type": "KSampler", "inputs": {}}})
        ops = json.dumps([{"op": "add_node", "class_type": "SaveImage"}])
        result = await tools["modify_workflow"](workflow=wf, operations=ops)
        modified = json.loads(result)
        assert "2" in modified

    async def test_invalid_workflow_json_raises(self, components):
        client, audit, limiter, inspector = components
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        ops = json.dumps([{"op": "add_node", "class_type": "SaveImage"}])
        with pytest.raises(ValueError, match="Invalid JSON"):
            await tools["modify_workflow"](workflow="not json", operations=ops)

    async def test_invalid_operations_json_raises(self, components):
        client, audit, limiter, inspector = components
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        wf = json.dumps({"1": {"class_type": "KSampler", "inputs": {}}})
        with pytest.raises(ValueError, match="Invalid JSON"):
            await tools["modify_workflow"](workflow=wf, operations="not json")


class TestValidateWorkflow:
    @respx.mock
    async def test_valid_workflow(self, components):
        client, audit, limiter, inspector = components
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={
                "KSampler": {"display_name": "KSampler", "input": {"required": {}}},
            })
        )
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        wf = json.dumps({"1": {"class_type": "KSampler", "inputs": {}}})
        result = await tools["validate_workflow"](workflow=wf)
        parsed = json.loads(result)
        assert parsed["valid"] is True

    async def test_invalid_json_raises(self, components):
        client, audit, limiter, inspector = components
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)
        with pytest.raises(ValueError, match="Invalid JSON"):
            await tools["validate_workflow"](workflow="not json")


class TestIntegration:
    @respx.mock
    async def test_create_modify_validate_roundtrip(self, components):
        client, audit, limiter, inspector = components
        respx.get("http://test:8188/object_info").mock(side_effect=httpx.ConnectError("offline"))
        mcp = FastMCP("test")
        tools = register_workflow_tools(mcp, client, audit, limiter, inspector)

        # Create
        created = await tools["create_workflow"](template="txt2img", params=json.dumps({"prompt": "a cat"}))
        wf = json.loads(created)

        # Modify — add a LoRA loader
        ops = json.dumps([
            {"op": "add_node", "node_id": "20", "class_type": "LoraLoader", "inputs": {"lora_name": "detail.safetensors"}},
        ])
        modified = await tools["modify_workflow"](workflow=json.dumps(wf), operations=ops)
        mod_wf = json.loads(modified)
        assert "20" in mod_wf

        # Validate
        validated = await tools["validate_workflow"](workflow=modified)
        result = json.loads(validated)
        assert result["node_count"] == len(mod_wf)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_workflow.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement tools/workflow.py**

Create `src/comfyui_mcp/tools/workflow.py`:

```python
"""Workflow composition tools: create_workflow, modify_workflow, validate_workflow."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.workflow.operations import apply_operations
from comfyui_mcp.workflow.templates import create_from_template
from comfyui_mcp.workflow.validation import validate_workflow as _validate_workflow


def register_workflow_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    inspector: WorkflowInspector,
) -> dict[str, Any]:
    """Register workflow composition tools."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool()
    async def create_workflow(template: str, params: str = "{}") -> str:
        """Create a ComfyUI workflow from a template with optional parameter overrides.

        Available templates: txt2img, img2img, upscale, inpaint, txt2vid_animatediff, txt2vid_wan.

        Args:
            template: Template name (e.g. 'txt2img', 'img2img')
            params: Optional JSON string of parameter overrides.
                    Common params: prompt, negative_prompt, width, height, steps, cfg, model, denoise.
        """
        limiter.check("create_workflow")
        try:
            param_dict = json.loads(params)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON params: {e}") from e

        wf = create_from_template(template, param_dict)
        audit.log(
            tool="create_workflow",
            action="created",
            extra={"template": template, "node_count": len(wf)},
        )
        return json.dumps(wf)

    tool_fns["create_workflow"] = create_workflow

    @mcp.tool()
    async def modify_workflow(workflow: str, operations: str) -> str:
        """Apply batch operations to a ComfyUI workflow.

        Operations: add_node, remove_node, set_input, connect, disconnect.
        Operations execute sequentially. If any fails, the workflow is unchanged.

        Args:
            workflow: JSON string of the workflow to modify.
            operations: JSON string of an array of operation objects.
                        Each has an 'op' field and operation-specific fields.
                        Example: [{"op": "add_node", "class_type": "LoraLoader"},
                                  {"op": "connect", "from_node": "1", "from_output": 0,
                                   "to_node": "3", "to_input": "model"}]
        """
        limiter.check("modify_workflow")
        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e
        try:
            ops = json.loads(operations)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON operations: {e}") from e

        result = apply_operations(wf, ops)
        audit.log(
            tool="modify_workflow",
            action="modified",
            extra={"operations": len(ops), "node_count": len(result)},
        )
        return json.dumps(result)

    tool_fns["modify_workflow"] = modify_workflow

    @mcp.tool()
    async def validate_workflow(workflow: str) -> str:
        """Validate a ComfyUI workflow for structural correctness, server compatibility, and security.

        Checks: node structure, connection references, installed node types,
        available models, dangerous nodes, and suspicious inputs.

        Args:
            workflow: JSON string of the workflow to validate.

        Returns:
            JSON string with: valid (bool), errors (list), warnings (list),
            node_count (int), pipeline (str).
        """
        limiter.check("validate_workflow")
        try:
            wf = json.loads(workflow)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON workflow: {e}") from e

        if not isinstance(wf, dict):
            raise ValueError("Workflow must be a JSON object keyed by node IDs")

        result = await _validate_workflow(wf, client, inspector)
        audit.log(
            tool="validate_workflow",
            action="validated",
            extra={
                "valid": result["valid"],
                "error_count": len(result["errors"]),
                "warning_count": len(result["warnings"]),
            },
        )
        return json.dumps(result)

    tool_fns["validate_workflow"] = validate_workflow

    return tool_fns
```

- [ ] **Step 4: Wire into server.py**

Add import at `src/comfyui_mcp/server.py:20`:

```python
from comfyui_mcp.tools.workflow import register_workflow_tools
```

Add registration call in `_register_all_tools()` after the `register_generation_tools` call (after line 87):

```python
    register_workflow_tools(server, client, audit, rate_limiters["read"], inspector)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_workflow.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 7: Lint and type check**

Run: `uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/comfyui_mcp/`

- [ ] **Step 8: Commit**

```bash
git add src/comfyui_mcp/tools/workflow.py src/comfyui_mcp/server.py tests/test_tools_workflow.py
git commit -m "feat: add create_workflow, modify_workflow, validate_workflow tools"
```

### Task 9: Update README tools table

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add new tools to the README tools table**

Add three rows to the tools table in `README.md`:

| Tool | Description |
|------|-------------|
| `create_workflow` | Create a workflow from a template (txt2img, img2img, upscale, inpaint, txt2vid_animatediff, txt2vid_wan) |
| `modify_workflow` | Apply batch operations (add_node, remove_node, set_input, connect, disconnect) to a workflow |
| `validate_workflow` | Validate workflow structure, server compatibility, and security |

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add workflow composition tools to README"
```

### Task 10: Final verification and PR

- [ ] **Step 1: Run full test suite with coverage**

Run: `uv run pytest --cov=src/comfyui_mcp --cov-report=term-missing -v`

- [ ] **Step 2: Run all pre-commit hooks**

Run: `uv run pre-commit run --all-files`

- [ ] **Step 3: Create PR**

```bash
git push -u origin feat/workflow-composition
gh pr create --title "feat: add workflow composition tools (create, modify, validate)" --body "$(cat <<'EOF'
## Summary

Closes #1

- `create_workflow` — build workflows from 6 templates (txt2img, img2img, upscale, inpaint, txt2vid_animatediff, txt2vid_wan) with parameter overrides
- `modify_workflow` — batch graph operations (add_node, remove_node, set_input, connect, disconnect) with atomic failure semantics
- `validate_workflow` — three-layer validation: structural checks, server compatibility (installed nodes, available models), and security inspection

## Architecture

New `src/comfyui_mcp/workflow/` package:
- `templates.py` — 6 workflow templates with param application
- `operations.py` — batch operation execution
- `validation.py` — structural + server + security validation (also hosts analysis utilities moved from generation.py)

Thin tool registration in `src/comfyui_mcp/tools/workflow.py`.

## Test plan

- [ ] All template types produce valid, wired workflows
- [ ] Parameter overrides apply correctly
- [ ] All 5 operations work individually and in batch
- [ ] Atomic failure: partial batch doesn't modify workflow
- [ ] Structural validation catches: missing class_type, broken connections, cycles
- [ ] Server validation catches: uninstalled nodes, missing models
- [ ] Security validation: dangerous node warnings, enforce mode blocking
- [ ] Graceful degradation when ComfyUI server unreachable
- [ ] Create → modify → validate round-trip works end-to-end

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
