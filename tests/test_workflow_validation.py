"""Tests for workflow validation."""

from __future__ import annotations

from typing import Any, ClassVar

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


def _mock_node_replacements() -> None:
    """Mock GET /node_replacements (returns empty — no replacements)."""
    respx.get("http://test:8188/node_replacements").mock(return_value=httpx.Response(200, json={}))


@pytest.fixture
def client():
    return ComfyUIClient(base_url="http://test:8188")


@pytest.fixture
def inspector():
    return WorkflowInspector(mode="audit", dangerous_nodes=["EvalNode"], allowed_nodes=[])


class TestStructuralValidation:
    @respx.mock
    async def test_valid_workflow_passes(self, client, inspector):
        object_info = {
            "CheckpointLoaderSimple": {
                "display_name": "Load Checkpoint",
                "input": {"required": {"ckpt_name": [["model.safetensors"]]}},
            },
            "CLIPTextEncode": {
                "display_name": "CLIP Text Encode",
                "input": {"required": {"text": ["STRING"], "clip": ["CLIP"]}},
            },
        }
        _mock_node_replacements()
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json=object_info)
        )
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["model.safetensors"])
        )
        result = await validate_workflow(_valid_workflow(), client, inspector)
        assert result["valid"] is True
        assert result["errors"] == []

    @respx.mock
    async def test_missing_class_type_is_error(self, client, inspector):
        wf = {"1": {"inputs": {"x": 1}}}
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("class_type" in e for e in result["errors"])

    @respx.mock
    async def test_broken_connection_is_error(self, client, inspector):
        _mock_node_replacements()
        wf = {
            "1": {
                "class_type": "KSampler",
                "inputs": {"model": ["99", 0]},
            },
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("99" in e for e in result["errors"])

    @respx.mock
    async def test_cycle_is_error(self, client, inspector):
        _mock_node_replacements()
        wf = {
            "1": {"class_type": "A", "inputs": {"x": ["2", 0]}},
            "2": {"class_type": "B", "inputs": {"x": ["1", 0]}},
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("cycle" in e.lower() for e in result["errors"])


class TestLoopNodeValidation:
    """Loop-boundary awareness (upstream CORE-14, Generic Loops)."""

    _OBJECT_INFO: ClassVar[dict[str, dict[str, Any]]] = {
        "StartLoop": {"display_name": "Start Loop", "category": "utilities/looping"},
        "EndLoop": {"display_name": "End Loop", "category": "utilities/looping"},
        "EmptyLatentImage": {"display_name": "Empty Latent"},
        "KSampler": {"display_name": "KSampler"},
        "SaveImage": {"display_name": "Save Image"},
    }

    def _mock_server(self, object_info=None):
        _mock_node_replacements()
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json=object_info or self._OBJECT_INFO)
        )

    @respx.mock
    async def test_paired_loop_passes(self, client, inspector):
        self._mock_server()
        # Legal pair mirroring upstream test_accepts_accumulate_control_from_outside_loop:
        # body flows into EndLoop via 'value'; accumulate is driven from OUTSIDE the loop
        # (the initial-carry pattern); output consumes the EndLoop result.
        wf = {
            "1": {"class_type": "StartLoop", "inputs": {"num_iterations": 4}},
            "2": {"class_type": "EmptyLatentImage", "inputs": {}},
            "3": {
                "class_type": "KSampler",
                "inputs": {"latent_image": ["2", 0], "model": ["1", 0]},
            },
            "4": {"class_type": "EndLoop", "inputs": {"value": ["3", 0], "accumulate": ["2", 0]}},
            "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0]}},
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is True
        assert not any("loop" in e.lower() for e in result["errors"])

    @respx.mock
    async def test_orphan_end_loop_is_error(self, client, inspector):
        self._mock_server()
        wf = {"1": {"class_type": "EndLoop", "inputs": {}}}
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("End Loop" in e and "Start Loop" in e for e in result["errors"])

    @respx.mock
    async def test_orphan_start_loop_is_error(self, client, inspector):
        self._mock_server()
        wf = {
            "1": {"class_type": "StartLoop", "inputs": {"num_iterations": 4}},
            "2": {"class_type": "EmptyLatentImage", "inputs": {}},
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("Start Loop" in e and "End Loop" in e for e in result["errors"])

    @respx.mock
    async def test_loop_escape_is_error(self, client, inspector):
        """A loop body node linked outside the loop without passing EndLoop
        (upstream 'loop_escape') is an error."""
        self._mock_server()
        wf = {
            "1": {"class_type": "StartLoop", "inputs": {"num_iterations": 4}},
            "2": {"class_type": "EmptyLatentImage", "inputs": {}},
            "3": {
                "class_type": "KSampler",
                "inputs": {"latent_image": ["2", 0], "model": ["1", 0]},
            },
            "4": {"class_type": "EndLoop", "inputs": {"accumulate": ["3", 0]}},
            "5": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("escape" in e.lower() for e in result["errors"])

    @respx.mock
    async def test_loop_accumulate_from_body_is_error(self, client, inspector):
        """EndLoop.accumulate driven by a node inside its own loop body is an
        error upstream (loop_accumulate_from_body)."""
        self._mock_server()
        wf = {
            "1": {"class_type": "StartLoop", "inputs": {"num_iterations": 4}},
            "2": {"class_type": "EmptyLatentImage", "inputs": {}},
            "3": {
                "class_type": "KSampler",
                "inputs": {"latent_image": ["2", 0], "model": ["1", 0]},
            },
            "4": {"class_type": "EndLoop", "inputs": {"accumulate": ["3", 0]}},
        }
        result = await validate_workflow(wf, client, inspector)
        assert any("accumulate" in e.lower() for e in result["errors"])


class TestV3ObjectInfoParsing:
    """Issue #114: /object_info payload shapes produced by V3-schema nodes
    (CORE V3 migration) must flow through validate/analyze without errors.

    V1-info of V3 nodes: display_name can be None, output_matchtypes is a
    list or None, DynamicCombo expands into {option: (type, config)} entries,
    inputs tuples carry config dicts instead of bare type strings.
    """

    _V3_OBJECT_INFO: ClassVar[dict[str, dict[str, Any]]] = {
        "StartLoop": {
            "input": {
                "required": {
                    "mode": {
                        "simple": [["INT", {"default": 4, "min": 0}]],
                        "For": [["INT", {"default": 0}]],
                    },
                }
            },
            "input_order": {"required": ["mode"]},
            "is_input_list": True,
            "output": ["start_loop_output"],
            "output_is_list": [True],
            "output_name": ["start_loop_output"],
            "output_tooltips": [None],
            "output_matchtypes": None,
            "name": "StartLoop",
            "display_name": None,  # V3 nodes can omit display names
            "description": "",
            "python_module": "comfy_extras.nodes_loop",
            "category": "utilities/looping",
            "output_node": False,
            "search_aliases": [],
            "essentials_category": None,
        },
        "EndLoop": {
            "input": {
                "required": {
                    "accumulate": ["BOOLEAN", {"default": False}],
                },
                "optional": {
                    "value": ["start_loop_output", {}],
                },
            },
            "input_order": {"required": ["accumulate"], "optional": ["value"]},
            "is_input_list": True,
            "output": ["output_value", "carry"],
            "output_is_list": [True, False],
            "output_name": ["output_value", "carry"],
            "output_tooltips": [None, None],
            "output_matchtypes": ["output_value", "carry"],
            "name": "EndLoop",
            "display_name": "End Loop",
            "category": "utilities/looping",
            "output_node": False,
        },
    }

    @respx.mock
    async def test_v3_object_info_validates_loop_workflow(self, client, inspector):
        _mock_node_replacements()
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json=self._V3_OBJECT_INFO)
        )
        wf = {
            "1": {
                "class_type": "StartLoop",
                "inputs": {"mode": ["simple", {"num_iterations": 4}]},
            },
            "2": {"class_type": "EndLoop", "inputs": {"accumulate": False, "value": ["1", 0]}},
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is True
        assert result["errors"] == []


class TestServerValidation:
    @respx.mock
    async def test_missing_node_type_is_error(self, client, inspector):
        _mock_node_replacements()
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(
                200,
                json={
                    "CheckpointLoaderSimple": {
                        "display_name": "Load Checkpoint",
                        "input": {"required": {}},
                    },
                },
            )
        )
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["model.safetensors"])
        )
        wf = _valid_workflow()  # Has CLIPTextEncode which is NOT in object_info
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is False
        assert any("CLIPTextEncode" in e and "not installed" in e for e in result["errors"])

    @respx.mock
    async def test_missing_model_is_warning(self, client, inspector):
        _mock_node_replacements()
        object_info = {
            "CheckpointLoaderSimple": {
                "display_name": "Load Checkpoint",
                "input": {"required": {"ckpt_name": [["other.safetensors"]]}},
            },
            "CLIPTextEncode": {
                "display_name": "CLIP Text Encode",
                "input": {"required": {"text": ["STRING"], "clip": ["CLIP"]}},
            },
        }
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json=object_info)
        )
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["other.safetensors"])
        )
        wf = _valid_workflow()  # Has model.safetensors which is NOT in models list
        result = await validate_workflow(wf, client, inspector)
        assert any("model.safetensors" in w for w in result["warnings"])

    @respx.mock
    async def test_server_unreachable_adds_warning(self, client, inspector):
        _mock_node_replacements()
        respx.get("http://test:8188/object_info").mock(side_effect=httpx.ConnectError("offline"))
        wf = _valid_workflow()
        result = await validate_workflow(wf, client, inspector)
        assert any("server" in w.lower() for w in result["warnings"])
        assert result["node_count"] == 2


class TestSecurityValidation:
    @respx.mock
    async def test_dangerous_node_adds_warning(self, client, inspector):
        _mock_node_replacements()
        respx.get("http://test:8188/object_info").mock(side_effect=httpx.ConnectError("offline"))
        wf = {"1": {"class_type": "EvalNode", "inputs": {}}}
        result = await validate_workflow(wf, client, inspector)
        assert any("Dangerous" in w for w in result["warnings"])

    @respx.mock
    async def test_enforce_mode_blocks(self, client):
        _mock_node_replacements()
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


class TestParallelModelChecks:
    @respx.mock
    async def test_multiple_model_loaders_checked(self, client, inspector):
        """Workflow with 2 loaders in different folders should check both."""
        _mock_node_replacements()
        object_info = {
            "CheckpointLoaderSimple": {"display_name": "Load Checkpoint"},
            "LoraLoader": {"display_name": "Load LoRA"},
        }
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json=object_info)
        )
        respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["model.safetensors"])
        )
        respx.get("http://test:8188/models/loras").mock(
            return_value=httpx.Response(200, json=["style.safetensors"])
        )
        wf = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"},
            },
            "2": {
                "class_type": "LoraLoader",
                "inputs": {
                    "lora_name": "missing.safetensors",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                    "model": ["1", 0],
                    "clip": ["1", 1],
                },
            },
        }
        result = await validate_workflow(wf, client, inspector)
        assert any("missing.safetensors" in w for w in result["warnings"])
        assert not any("model.safetensors" in w for w in result["warnings"])

    @respx.mock
    async def test_duplicate_folders_fetched_once(self, client, inspector):
        """Two checkpoint loaders should only trigger one /models/checkpoints call."""
        _mock_node_replacements()
        object_info = {
            "CheckpointLoaderSimple": {"display_name": "Load Checkpoint"},
        }
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json=object_info)
        )
        route = respx.get("http://test:8188/models/checkpoints").mock(
            return_value=httpx.Response(200, json=["a.safetensors", "b.safetensors"])
        )
        wf = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "a.safetensors"},
            },
            "2": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "b.safetensors"},
            },
        }
        result = await validate_workflow(wf, client, inspector)
        assert result["valid"] is True
        assert route.call_count == 1
