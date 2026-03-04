"""Tests for node danger auditor."""

from comfyui_mcp.security.node_auditor import (
    NodeAuditor,
)


class TestNodeAuditor:
    def test_audits_dangerous_name_patterns(self):
        auditor = NodeAuditor()

        node_info = {
            "input": {},
            "output": ["STRING"],
            "description": "Executes python code",
        }

        result = auditor.audit_node_class("RunPython", node_info)
        assert result is not None
        assert result.category == "dangerous"
        assert "python" in result.reason.lower()

    def test_audits_python_node(self):
        auditor = NodeAuditor()

        node_info = {"input": {}, "output": ["STRING"]}

        result = auditor.audit_node_class("RunPython", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_audits_dangerous_input_type(self):
        auditor = NodeAuditor()

        node_info = {
            "input": {
                "code": {
                    "type": "CODE",
                    "required": True,
                }
            },
            "output": ["STRING"],
        }

        result = auditor.audit_node_class("SafeLookingNode", node_info)
        assert result is not None
        assert result.category == "dangerous"
        assert "CODE" in result.reason

    def test_audits_suspicious_by_description(self):
        auditor = NodeAuditor()

        node_info = {
            "input": {"text": {"type": "STRING"}},
            "output": ["STRING"],
            "description": "Can execute arbitrary code in your workflow",
        }

        result = auditor.audit_node_class("SomeWildcardNode", node_info)
        assert result is not None
        assert result.category == "suspicious"

    def test_safe_node_returns_none(self):
        auditor = NodeAuditor()

        node_info = {
            "input": {"text": {"type": "STRING"}},
            "output": ["IMAGE"],
            "description": "A simple text encoder",
        }

        result = auditor.audit_node_class("CLIPTextEncode", node_info)
        assert result is None

    def test_common_safe_nodes_not_flagged(self):
        """Verify common ComfyUI nodes are not flagged as dangerous."""
        auditor = NodeAuditor()
        safe_node_info = {"input": {}, "output": ["IMAGE"]}

        safe_nodes = [
            "SaveImage",
            "LoadImage",
            "PreviewImage",
            "KSampler",
            "VAEDecode",
            "VAEEncode",
            "CheckpointLoaderSimple",
            "LoraLoader",
            "ImageUpscaleWithModel",
        ]
        for node_name in safe_nodes:
            result = auditor.audit_node_class(node_name, safe_node_info)
            assert result is None, f"{node_name} was incorrectly flagged: {result}"

    def test_handles_list_input_type(self):
        auditor = NodeAuditor()

        node_info = {
            "input": {
                "text": ["STRING", "STRING"],  # Some nodes have list types
            },
            "output": ["STRING"],
        }

        result = auditor.audit_node_class("SomeNode", node_info)
        assert result is None

    def test_handles_missing_input(self):
        auditor = NodeAuditor()

        node_info = {"output": ["STRING"]}

        result = auditor.audit_node_class("SomeNode", node_info)
        assert result is None

    def test_handles_missing_description(self):
        auditor = NodeAuditor()

        node_info = {"input": {}, "output": ["STRING"]}

        result = auditor.audit_node_class("SomeNode", node_info)
        assert result is None

    def test_flags_http_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["IMAGE"]}
        result = auditor.audit_node_class("Image Send HTTP", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_flags_request_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["STRING"]}
        result = auditor.audit_node_class("Get Request Node", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_flags_file_path_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["STRING"]}
        result = auditor.audit_node_class("CustomFilePath", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_flags_load_file_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["STRING"]}
        result = auditor.audit_node_class("Load Text File", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_flags_save_file_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["STRING"]}
        result = auditor.audit_node_class("Save Text File", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_flags_interpreter_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["STRING"]}
        result = auditor.audit_node_class("interpreter_tool", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_flags_python_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["STRING"]}
        result = auditor.audit_node_class("KY_Eval_Python", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_flags_url_input_type(self):
        auditor = NodeAuditor()
        node_info = {
            "input": {"target": {"type": "URL"}},
            "output": ["STRING"],
        }
        result = auditor.audit_node_class("SafeLookingNode", node_info)
        assert result is not None
        assert "URL" in result.reason

    def test_flags_file_path_input_type(self):
        auditor = NodeAuditor()
        node_info = {
            "input": {"path": {"type": "FILE_PATH"}},
            "output": ["STRING"],
        }
        result = auditor.audit_node_class("SafeLookingNode", node_info)
        assert result is not None
        assert "FILE_PATH" in result.reason

    def test_flags_script_input_type(self):
        auditor = NodeAuditor()
        node_info = {
            "input": {"code": {"type": "SCRIPT"}},
            "output": ["STRING"],
        }
        result = auditor.audit_node_class("SafeLookingNode", node_info)
        assert result is not None
        assert "SCRIPT" in result.reason

    def test_flags_download_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["IMAGE"]}
        result = auditor.audit_node_class("Download Image", node_info)
        assert result is not None
        assert result.category == "dangerous"

    def test_flags_fetch_pattern(self):
        auditor = NodeAuditor()
        node_info = {"input": {}, "output": ["STRING"]}
        result = auditor.audit_node_class("Fetch URL", node_info)
        assert result is not None
        assert result.category == "dangerous"


class TestAuditAllNodes:
    def test_audits_full_node_list(self):
        auditor = NodeAuditor()

        object_info = {
            "KSampler": {
                "input": {"seed": {"type": "INT"}},
                "output": ["LATENT"],
            },
            "RunPython": {
                "input": {"code": {"type": "CODE"}},
                "output": ["*"],
            },
            "CLIPTextEncode": {
                "input": {"text": {"type": "STRING"}},
                "output": ["CLIP"],
            },
        }

        result = auditor.audit_all_nodes(object_info)

        assert result.total_nodes == 3
        assert result.dangerous_count == 1
        assert result.suspicious_count == 0
        assert result.dangerous_nodes[0].node_class == "RunPython"

    def test_empty_node_list(self):
        auditor = NodeAuditor()

        result = auditor.audit_all_nodes({})

        assert result.total_nodes == 0
        assert result.dangerous_count == 0
        assert result.suspicious_count == 0

    def test_filters_non_dict_nodes(self):
        auditor = NodeAuditor()

        object_info = {
            "ValidNode": {"input": {}},
            "InvalidNode": "not a dict",
        }

        result = auditor.audit_all_nodes(object_info)

        assert result.total_nodes == 2
        assert result.dangerous_count == 0
