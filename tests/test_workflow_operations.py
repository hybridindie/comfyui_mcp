"""Tests for workflow graph operations."""

from __future__ import annotations

import copy
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
        ops = [
            {
                "op": "add_node",
                "node_id": "10",
                "class_type": "VAEDecode",
                "inputs": {"samples": ["1", 0]},
            }
        ]
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


class TestRemoveNode:
    def test_remove_existing_node(self):
        wf = _simple_workflow()
        ops = [{"op": "remove_node", "node_id": "2"}]
        result = apply_operations(wf, ops)
        assert "2" not in result
        assert "1" in result

    def test_remove_cleans_dangling_references(self):
        wf = _simple_workflow()
        wf["3"] = {"class_type": "KSampler", "inputs": {"positive": ["2", 0], "steps": 20}}
        ops = [{"op": "remove_node", "node_id": "2"}]
        result = apply_operations(wf, ops)
        assert "2" not in result
        assert "positive" not in result["3"]["inputs"]
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
        ops = [
            {
                "op": "connect",
                "from_node": "1",
                "from_output": 0,
                "to_node": "2",
                "to_input": "model",
            }
        ]
        result = apply_operations(wf, ops)
        assert result["2"]["inputs"]["model"] == ["1", 0]

    def test_connect_nonexistent_from_raises(self):
        wf = _simple_workflow()
        ops = [
            {
                "op": "connect",
                "from_node": "99",
                "from_output": 0,
                "to_node": "2",
                "to_input": "model",
            }
        ]
        with pytest.raises(ValueError, match="not found"):
            apply_operations(wf, ops)

    def test_connect_nonexistent_to_raises(self):
        wf = _simple_workflow()
        ops = [
            {
                "op": "connect",
                "from_node": "1",
                "from_output": 0,
                "to_node": "99",
                "to_input": "model",
            }
        ]
        with pytest.raises(ValueError, match="not found"):
            apply_operations(wf, ops)


class TestDisconnect:
    def test_disconnect_input(self):
        wf = _simple_workflow()
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


class TestBatchBehavior:
    def test_operations_apply_sequentially(self):
        """Adding a node then connecting to it should work."""
        wf = _simple_workflow()
        ops = [
            {"op": "add_node", "node_id": "3", "class_type": "VAEDecode"},
            {
                "op": "connect",
                "from_node": "1",
                "from_output": 2,
                "to_node": "3",
                "to_input": "vae",
            },
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
