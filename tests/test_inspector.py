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

# All cloud API node class_types, grouped by vendor (16 vendors, 135 total).
# Extracted from comfy/api_nodes/ (PR #9129, merged Aug 8, 2025).
_CLOUD_API_NODES: list[str] = [
    # BFL (Black Forest Labs / Flux)
    "FluxProUltraImageNode",
    "FluxProExpandNode",
    "FluxProFillNode",
    "FluxEraseNode",
    "FluxVTONode",
    "Flux2ImageNode",
    "Flux3TextToVideoNode",
    "Flux3ImageToVideoNode",
    "Flux3VideoContinuationNode",
    # Gemini (Google)
    "GeminiNode",
    "GeminiNodeV2",
    "GeminiInputFiles",
    "GeminiImageNode",
    "GeminiImage2Node",
    "GeminiNanoBanana2",
    "GeminiNanoBanana2V2",
    "GeminiVideoOmni",
    # Ideogram
    "IdeogramV3",
    "IdeogramV4",
    "IdeogramPImage",
    # Kling
    "KlingTextToVideoNode",
    "KlingOmniProTextToVideoNode",
    "KlingOmniProFirstLastFrameNode",
    "KlingOmniProImageToVideoNode",
    "KlingOmniProVideoToVideoNode",
    "KlingOmniProEditVideoNode",
    "KlingOmniProImageNode",
    "KlingImage2VideoNode",
    "KlingStartEndFrameNode",
    "KlingVideoExtendNode",
    "KlingLipSyncAudioToVideoNode",
    "KlingLipSyncTextToVideoNode",
    "KlingImageGenerationNode",
    "KlingTextToVideoWithAudio",
    "KlingImageToVideoWithAudio",
    "KlingMotionControl",
    "KlingVideoNode",
    "KlingFirstLastFrameNode",
    "KlingAvatarNode",
    # Luma
    "LumaReferenceNode",
    "LumaConceptsNode",
    "LumaImageNode",
    "LumaImageModifyNode",
    "LumaVideoNode",
    "LumaImageToVideoNode",
    "LumaImageNode2",
    "LumaImageEditNode2",
    "LumaRay32TextToVideoNode",
    "LumaRay32ImageToVideoNode",
    "LumaRay32KeyframeNode",
    "LumaRay32KeyframesToVideoNode",
    "LumaRay32VideoEditNode",
    "LumaRay32VideoReframeNode",
    "LumaRay32ExtendVideoNode",
    # Minimax
    "MinimaxTextToVideoNode",
    "MinimaxImageToVideoNode",
    "MinimaxSubjectToVideoNode",
    "MinimaxHailuoVideoNode",
    "MinimaxHailuo03TextToVideoNode",
    "MinimaxHailuo03FirstLastFrameNode",
    "MinimaxHailuo03ReferenceNode",
    # Moonvalley
    "MoonvalleyImg2VideoNode",
    "MoonvalleyTxt2VideoNode",
    "MoonvalleyVideo2VideoNode",
    # OpenAI
    "OpenAIDalle2",
    "OpenAIDalle3",
    "OpenAIGPTImage1",
    "OpenAIGPTImageNodeV2",
    "OpenAIChatNode",
    "OpenAIInputFiles",
    "OpenAIChatConfig",
    # Pika
    "PikaImageToVideoNode2_2",
    "PikaTextToVideoNode2_2",
    "PikaScenesV2_2",
    "Pikadditions",
    "Pikaswaps",
    "Pikaffects",
    "PikaStartEndFrameNode2_2",
    # PixVerse
    "PixverseTemplateNode",
    "PixverseTextToVideoNode",
    "PixverseImageToVideoNode",
    "PixverseTransitionVideoNode",
    # Recraft
    "RecraftColorRGB",
    "RecraftControls",
    "RecraftStyleV3RealisticImage",
    "RecraftStyleV3DigitalIllustration",
    "RecraftStyleV3VectorIllustrationNode",
    "RecraftStyleV3LogoRaster",
    "RecraftStyleV3InfiniteStyleLibrary",
    "RecraftCreateStyleNode",
    "RecraftTextToImageNode",
    "RecraftImageToImageNode",
    "RecraftImageInpaintingNode",
    "RecraftTextToVectorNode",
    "RecraftVectorizeImageNode",
    "RecraftReplaceBackgroundNode",
    "RecraftRemoveBackgroundNode",
    "RecraftCrispUpscaleNode",
    "RecraftCreativeUpscaleNode",
    "RecraftV4TextToImageNode",
    "RecraftV4TextToVectorNode",
    # Rodin (3D generation)
    "Rodin3D_Regular",
    "Rodin3D_Detail",
    "Rodin3D_Smooth",
    "Rodin3D_Sketch",
    "Rodin3D_Gen2",
    "Rodin3D_Gen25_Image",
    "Rodin3D_Gen25_Text",
    # Runway
    "RunwayImageToVideoNodeGen3a",
    "RunwayImageToVideoNodeGen4",
    "RunwayFirstLastFrameNode",
    "RunwayTextToImageNode",
    "RunwayAleph2KeyframeNode",
    "RunwayAleph2PromptImageNode",
    "RunwayAleph2VideoToVideoNode",
    # Stability AI
    "StabilityStableImageUltraNode",
    "StabilityStableImageSD_3_5Node",
    "StabilityUpscaleConservativeNode",
    "StabilityUpscaleCreativeNode",
    "StabilityUpscaleFastNode",
    # Tripo (3D generation)
    "TripoTextToModelNode",
    "TripoImageToModelNode",
    "TripoMultiviewToModelNode",
    "TripoTextureNode",
    "TripoRefineNode",
    "TripoRigNode",
    "TripoRetargetNode",
    "TripoConversionNode",
    "TripoImportModelNode",
    "TripoP1TextToModelNode",
    "TripoP1ImageToModelNode",
    "TripoP1MultiviewToModelNode",
    # Veo2 / Veo3 (Google)
    "VeoVideoGenerationNode",
    "Veo3VideoGenerationNode",
    "Veo3FirstLastFrameNode",
]

# One representative per vendor, for targeted inspector-flag tests.
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

    def test_all_cloud_api_nodes_in_default_dangerous_list(self):
        """Every cloud API node class_type must be in _DEFAULT_DANGEROUS_NODES."""
        missing = [n for n in _CLOUD_API_NODES if n not in _DEFAULT_DANGEROUS_NODES]
        assert not missing, (
            f"{len(missing)} cloud API node(s) missing from _DEFAULT_DANGEROUS_NODES: {missing}"
        )

    def test_cloud_api_node_count_matches(self):
        """Verify the documented count matches the actual list length."""
        cloud_count = sum(1 for n in _CLOUD_API_NODES)
        assert cloud_count == 135, (
            f"Expected 135 cloud API nodes, got {cloud_count} — update the count "
            f"in CHANGELOG/README if ComfyUI added/removed nodes"
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

    def test_inspector_flags_all_cloud_api_nodes(self):
        """Every cloud API node must trigger a warning from the inspector."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=list(_DEFAULT_DANGEROUS_NODES),
            allowed_nodes=[],
        )
        for node_type in _CLOUD_API_NODES:
            workflow = _make_workflow(node_type)
            result = inspector.inspect(workflow)
            assert any(node_type in w for w in result.warnings), (
                f"Cloud API node {node_type} was not flagged by the inspector"
            )


# ---------------------------------------------------------------------------
# #110 — subgraphs can hide nodes from the inspector. A submitted workflow
# may contain subgraph references whose internal nodes are not present at the
# top level. The inspector must at minimum warn that inspection is incomplete.
# ---------------------------------------------------------------------------


def _make_subgraph_workflow() -> dict:
    """Build a workflow with a subgraph node referencing an internal graph.

    ComfyUI subgraphs embed the nested node map under the subgraph node's
    ``inputs`` or a ``subgraph`` key. This shape mirrors the real structure:
    the top-level node map has a ``Reroute_subgraph`` entry whose ``inputs``
    contains the nested nodes.
    """
    return {
        "1": {
            "class_type": "KSampler",
            "inputs": {"cfg": 7.0},
        },
        "2": {
            "class_type": "Reroute_subgraph",
            "inputs": {
                "subgraph": {
                    "10": {
                        "class_type": "Terminal",  # dangerous — must be detected
                        "inputs": {},
                    },
                    "11": {
                        "class_type": "KSampler",
                        "inputs": {"cfg": 8.0},
                    },
                },
            },
        },
    }


def _make_unexpanded_subgraph_workflow() -> dict:
    """Build a workflow with a subgraph node that has no inline node map.

    The subgraph is referenced by ID only — its internal nodes are not present
    in the submitted JSON. The inspector cannot fully inspect this and must
    warn.
    """
    return {
        "1": {
            "class_type": "KSampler",
            "inputs": {"cfg": 7.0},
        },
        "2": {
            "class_type": "Reroute_subgraph",
            "inputs": {
                "subgraph_id": "abc123",  # reference only, no inline nodes
            },
        },
    }


class TestSubgraphInspection:
    """#110: the inspector must recurse into (or at least warn about) subgraphs."""

    def test_inspector_warns_about_unexpanded_subgraph(self):
        """The inspector must emit a warning when a workflow contains a subgraph
        node it cannot fully inspect."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=["Terminal"],
            allowed_nodes=[],
        )
        workflow = _make_unexpanded_subgraph_workflow()
        result = inspector.inspect(workflow)
        assert any("subgraph" in w.lower() for w in result.warnings), (
            "Workflow with an unexpanded subgraph node produced no subgraph warning "
            "— the inspector silently skips nested nodes (issue #110)"
        )

    def test_inspector_detects_dangerous_node_inside_subgraph(self):
        """A dangerous node nested inside a subgraph must be flagged."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=["Terminal"],
            allowed_nodes=[],
        )
        workflow = _make_subgraph_workflow()
        result = inspector.inspect(workflow)
        assert any("Terminal" in w for w in result.warnings), (
            "Dangerous node 'Terminal' inside a subgraph was not detected — "
            "inspection-evasion via subgraphs (issue #110)"
        )

    def test_inspector_detects_suspicious_input_inside_subgraph(self):
        """Suspicious input patterns inside a subgraph must be flagged."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=[],
            allowed_nodes=[],
        )
        workflow = {
            "1": {
                "class_type": "Reroute_subgraph",
                "inputs": {
                    "subgraph": {
                        "5": {
                            "class_type": "CustomNode",
                            "inputs": {
                                "code": "__import__('os').system('rm -rf /')",
                            },
                        },
                    },
                },
            },
        }
        result = inspector.inspect(workflow)
        assert any("suspicious" in w.lower() for w in result.warnings), (
            "Suspicious input inside a subgraph was not detected (issue #110)"
        )

    def test_inspector_collects_nodes_used_inside_subgraph(self):
        """class_types inside a subgraph must appear in nodes_used."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=[],
            allowed_nodes=[],
        )
        workflow = _make_subgraph_workflow()
        result = inspector.inspect(workflow)
        assert "Terminal" in result.nodes_used, (
            "class_type 'Terminal' inside a subgraph was not collected in "
            "nodes_used — the inspector skips subgraph contents (issue #110)"
        )

    def test_enforce_mode_blocks_dangerous_node_inside_subgraph(self):
        """In enforce mode, a dangerous node inside a subgraph must block."""
        inspector = WorkflowInspector(
            mode="enforce",
            dangerous_nodes=["Terminal"],
            allowed_nodes=["KSampler", "Reroute_subgraph"],
        )
        workflow = _make_subgraph_workflow()
        with pytest.raises(WorkflowBlockedError, match="Terminal"):
            inspector.inspect(workflow)
