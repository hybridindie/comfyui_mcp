"""Tests for workflow inspection."""

import pytest

from comfyui_mcp.config import _DEFAULT_DANGEROUS_NODES
from comfyui_mcp.security.inspector import (
    WorkflowBlockedError,
    WorkflowInspector,
)


def _make_workflow(*node_types: str) -> dict:
    """Helper to build a minimal ComfyUI workflow dict."""
    workflow = {}
    for i, node_type in enumerate(node_types):
        workflow[str(i)] = {
            "class_type": node_type,
            "inputs": {},
        }
    return workflow


class TestWorkflowInspector:
    @pytest.fixture
    def audit_inspector(self):
        return WorkflowInspector(
            mode="audit",
            dangerous_nodes=["Terminal", "KY_Eval_Python"],
            allowed_nodes=[],
        )

    @pytest.fixture
    def enforce_inspector(self):
        return WorkflowInspector(
            mode="enforce",
            dangerous_nodes=["Terminal"],
            allowed_nodes=["KSampler", "CLIPTextEncode", "VAEDecode", "SaveImage"],
        )

    def test_audit_mode_extracts_node_types(self, audit_inspector):
        workflow = _make_workflow("KSampler", "CLIPTextEncode", "VAEDecode")
        result = audit_inspector.inspect(workflow)
        assert set(result.nodes_used) == {"KSampler", "CLIPTextEncode", "VAEDecode"}

    def test_audit_mode_flags_dangerous_nodes(self, audit_inspector):
        workflow = _make_workflow("KSampler", "Terminal")
        result = audit_inspector.inspect(workflow)
        assert len(result.warnings) > 0
        assert any("Terminal" in w for w in result.warnings)

    def test_audit_mode_never_blocks(self, audit_inspector):
        workflow = _make_workflow("Terminal", "KY_Eval_Python")
        result = audit_inspector.inspect(workflow)
        assert len(result.warnings) > 0

    def test_enforce_mode_allows_approved_nodes(self, enforce_inspector):
        workflow = _make_workflow("KSampler", "CLIPTextEncode")
        result = enforce_inspector.inspect(workflow)
        assert len(result.warnings) == 0

    def test_enforce_mode_blocks_unapproved_nodes(self, enforce_inspector):
        workflow = _make_workflow("KSampler", "UnknownCustomNode")
        with pytest.raises(WorkflowBlockedError, match="UnknownCustomNode"):
            enforce_inspector.inspect(workflow)

    def test_enforce_mode_blocks_dangerous_nodes(self, enforce_inspector):
        workflow = _make_workflow("KSampler", "Terminal")
        with pytest.raises(WorkflowBlockedError, match="Terminal"):
            enforce_inspector.inspect(workflow)

    def test_empty_workflow(self, audit_inspector):
        result = audit_inspector.inspect({})
        assert result.nodes_used == []
        assert result.warnings == []

    def test_suspicious_input_flagged(self, audit_inspector):
        workflow = {
            "0": {
                "class_type": "KSampler",
                "inputs": {"code": "__import__('os').system('rm -rf /')"},
            }
        }
        result = audit_inspector.inspect(workflow)
        assert any("suspicious" in w.lower() for w in result.warnings)

    def test_suspicious_input_nested_in_dict(self, audit_inspector):
        workflow = {
            "0": {
                "class_type": "CustomNode",
                "inputs": {
                    "config": {"script": "exec('malicious')"},
                },
            }
        }
        result = audit_inspector.inspect(workflow)
        assert any("suspicious" in w.lower() for w in result.warnings)

    def test_suspicious_input_nested_in_list(self, audit_inspector):
        workflow = {
            "0": {
                "class_type": "CustomNode",
                "inputs": {
                    "scripts": ["safe", "__import__('os').system('whoami')"],
                },
            }
        }
        result = audit_inspector.inspect(workflow)
        assert any("suspicious" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# #109 — first-party ComfyUI cloud API nodes must be flagged (network egress
# + cost). These class_types ship in ComfyUI core (PR #9129) and send user
# prompts/images to paid third-party services from the ComfyUI host.
# ---------------------------------------------------------------------------

# Representative sample — one per vendor (16 vendors, 109 total nodes).
_CLOUD_API_NODE_SAMPLES = [
    "FluxProUltraImageNode",  # BFL
    "GeminiNode",  # Gemini
    "IdeogramV3",  # Ideogram
    "KlingTextToVideoNode",  # Kling
    "LumaImageNode",  # Luma
    "MinimaxTextToVideoNode",  # Minimax
    "MoonvalleyTxt2VideoNode",  # Moonvalley
    "OpenAIDalle3",  # OpenAI
    "PikaTextToVideoNode2_2",  # Pika
    "PixverseTextToVideoNode",  # PixVerse
    "RecraftTextToImageNode",  # Recraft
    "Rodin3D_Regular",  # Rodin
    "RunwayImageToVideoNodeGen4",  # Runway
    "StabilityStableImageUltraNode",  # Stability AI
    "TripoTextToModelNode",  # Tripo
    "VeoVideoGenerationNode",  # Veo2 (Google)
]


class TestCloudApiNodesDangerous:
    """#109: first-party cloud API nodes must be in the dangerous-nodes list."""

    def test_cloud_api_nodes_in_default_dangerous_list(self):
        """Every sampled cloud API node must be in _DEFAULT_DANGEROUS_NODES."""
        missing = [n for n in _CLOUD_API_NODE_SAMPLES if n not in _DEFAULT_DANGEROUS_NODES]
        assert not missing, (
            f"{len(missing)} cloud API node(s) missing from _DEFAULT_DANGEROUS_NODES: {missing}"
        )

    def test_inspector_flags_cloud_api_node(self):
        """The inspector must warn when a workflow uses a cloud API node."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=list(_DEFAULT_DANGEROUS_NODES),
            allowed_nodes=[],
        )
        workflow = _make_workflow("KSampler", "KlingTextToVideoNode")
        result = inspector.inspect(workflow)
        assert any("KlingTextToVideoNode" in w for w in result.warnings), (
            "Cloud API node KlingTextToVideoNode was not flagged — data exfiltration "
            "and cost risk goes unwarned (issue #109)"
        )

    def test_inspector_flags_all_sampled_cloud_api_nodes(self):
        """Every sampled cloud API node must trigger a warning."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=list(_DEFAULT_DANGEROUS_NODES),
            allowed_nodes=[],
        )
        for node_type in _CLOUD_API_NODE_SAMPLES:
            workflow = _make_workflow(node_type)
            result = inspector.inspect(workflow)
            assert any(node_type in w for w in result.warnings), (
                f"Cloud API node {node_type} was not flagged by the inspector"
            )
