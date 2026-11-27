"""Declarative workflow policy (issue #211)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import ValidationError

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.config import SecurityPolicySettings
from comfyui_mcp.security.inspector import (
    WorkflowBlockedError,
    WorkflowInspector,
    WorkflowPolicy,
)
from comfyui_mcp.tools.generation import _submit_workflow


def _wf(*class_types: str) -> dict:
    return {
        str(index): {"class_type": class_type, "inputs": {}}
        for index, class_type in enumerate(class_types, start=1)
    }


def _loader_workflow(folder_value: str = "m.safetensors") -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": folder_value}},
    }


class TestPolicyConfig:
    def test_defaults_preserve_current_behavior(self):
        policy = SecurityPolicySettings()

        assert policy.on_warning == "elicit"
        assert policy.deny_nodes == []
        assert policy.warn_nodes == []
        assert policy.max_nodes == 0
        assert policy.allowed_model_folders == []

    def test_unknown_keys_are_rejected(self):
        with pytest.raises(ValidationError):
            SecurityPolicySettings(deny_node=["typo"])

    def test_invalid_on_warning_is_rejected(self):
        with pytest.raises(ValidationError):
            SecurityPolicySettings(on_warning="ignore")

    def test_negative_max_nodes_is_rejected(self):
        with pytest.raises(ValidationError):
            SecurityPolicySettings(max_nodes=-1)


class TestInspectorPolicy:
    def test_deny_hard_blocks_in_enforce(self):
        inspector = WorkflowInspector(
            mode="enforce",
            policy=WorkflowPolicy(deny_nodes=frozenset({"ExecutePython"})),
        )

        with pytest.raises(WorkflowBlockedError, match="policy denied node type"):
            inspector.inspect(_wf("ExecutePython"))

    def test_deny_warns_in_audit(self):
        inspector = WorkflowInspector(
            mode="audit",
            policy=WorkflowPolicy(deny_nodes=frozenset({"ExecutePython"})),
        )

        result = inspector.inspect(_wf("ExecutePython"))

        assert any("policy denied node type" in warning for warning in result.warnings)

    def test_warn_nodes_adds_a_warning(self):
        inspector = WorkflowInspector(
            mode="audit",
            policy=WorkflowPolicy(warn_nodes=frozenset({"CheckpointLoaderSimple"})),
        )

        result = inspector.inspect(_loader_workflow())

        assert "Policy warning node: CheckpointLoaderSimple" in result.warnings

    def test_max_nodes_counts_nested_subgraph_nodes(self):
        workflow = {
            "1": {
                "class_type": "Reroute_subgraph",
                "inputs": {
                    "subgraph": {
                        "2": {"class_type": "KSampler", "inputs": {}},
                        "3": {"class_type": "VAEDecode", "inputs": {}},
                    }
                },
            }
        }
        inspector = WorkflowInspector(
            mode="enforce",
            policy=WorkflowPolicy(max_nodes=2),
        )

        with pytest.raises(WorkflowBlockedError, match="max_nodes"):
            inspector.inspect(workflow)

    def test_max_nodes_warns_in_audit(self):
        inspector = WorkflowInspector(mode="audit", policy=WorkflowPolicy(max_nodes=1))

        result = inspector.inspect(_wf("KSampler", "VAEDecode"))

        assert any("max_nodes" in warning for warning in result.warnings)

    def test_model_folder_violation_blocks_in_enforce(self):
        inspector = WorkflowInspector(
            mode="enforce",
            policy=WorkflowPolicy(allowed_model_folders=frozenset({"loras"})),
        )

        with pytest.raises(WorkflowBlockedError, match="model folders"):
            inspector.inspect(_loader_workflow())

    def test_allowed_model_folder_passes(self):
        inspector = WorkflowInspector(
            mode="enforce",
            policy=WorkflowPolicy(allowed_model_folders=frozenset({"checkpoints"})),
        )

        result = inspector.inspect(_loader_workflow())

        assert not any("model folders" in warning for warning in result.warnings)

    def test_model_folder_violation_inside_subgraph_is_caught(self):
        workflow = {
            "1": {
                "class_type": "Reroute_subgraph",
                "inputs": {
                    "subgraph": {
                        "2": {
                            "class_type": "CheckpointLoaderSimple",
                            "inputs": {"ckpt_name": "m.safetensors"},
                        }
                    }
                },
            }
        }
        inspector = WorkflowInspector(
            mode="enforce",
            policy=WorkflowPolicy(allowed_model_folders=frozenset({"loras"})),
        )

        with pytest.raises(WorkflowBlockedError, match="model folders"):
            inspector.inspect(workflow)

    def test_empty_policy_is_not_configured_and_changes_nothing(self):
        inspector = WorkflowInspector(mode="audit", dangerous_nodes=["KSampler"])

        result = inspector.inspect(_wf("KSampler"))

        assert inspector.policy.is_configured is False
        assert "Dangerous node type: KSampler" in result.warnings
        assert not any(warning.startswith("Policy") for warning in result.warnings)

    def test_describe_is_json_safe(self):
        policy = WorkflowPolicy(
            deny_nodes=frozenset({"A"}),
            warn_nodes=frozenset({"B"}),
            on_warning="block",
            max_nodes=10,
            allowed_model_folders=frozenset({"checkpoints"}),
        )

        assert policy.describe() == {
            "deny_nodes": ["A"],
            "warn_nodes": ["B"],
            "on_warning": "block",
            "max_nodes": 10,
            "allowed_model_folders": ["checkpoints"],
        }


def _warning_workflow() -> dict:
    return {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat"}}}


@pytest.fixture
def deps(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    return client, audit


def _inspector(on_warning: str) -> WorkflowInspector:
    return WorkflowInspector(
        mode="enforce",
        policy=WorkflowPolicy(
            warn_nodes=frozenset({"CLIPTextEncode"}),
            on_warning=on_warning,
        ),
    )


class TestSubmissionGate:
    @respx.mock
    async def test_block_raises_without_eliciting(self, deps):
        client, audit = deps
        prompt_route = respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc"})
        )

        with pytest.raises(WorkflowBlockedError, match="blocked by policy"):
            await _submit_workflow(
                wf=_warning_workflow(),
                tool_name="run_workflow",
                success_message="ok",
                wait=False,
                client=client,
                audit=audit,
                inspector=_inspector("block"),
                progress=None,
            )

        assert not prompt_route.called

    @respx.mock
    async def test_allow_submits_and_keeps_warnings(self, deps):
        client, audit = deps
        route = respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc"})
        )

        result = await _submit_workflow(
            wf=_warning_workflow(),
            tool_name="run_workflow",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=_inspector("allow"),
            progress=None,
        )

        assert route.called
        assert result["status"] == "submitted"
        assert result["warnings"]

    @respx.mock
    async def test_policy_snapshot_is_audited(self, deps, tmp_path):
        client, audit = deps
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc"})
        )

        await _submit_workflow(
            wf=_warning_workflow(),
            tool_name="run_workflow",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=_inspector("allow"),
            progress=None,
        )

        records = [
            json.loads(line) for line in (tmp_path / "audit.log").read_text().splitlines() if line
        ]
        inspected = next(r for r in records if r["action"] == "inspected")
        assert inspected["extra"]["policy"]["on_warning"] == "allow"
        assert inspected["extra"]["policy"]["warn_nodes"] == ["CLIPTextEncode"]

    @respx.mock
    async def test_deny_blocks_before_the_gate(self, deps):
        client, audit = deps
        prompt_route = respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc"})
        )
        inspector = WorkflowInspector(
            mode="enforce",
            policy=WorkflowPolicy(deny_nodes=frozenset({"CLIPTextEncode"}), on_warning="allow"),
        )

        with pytest.raises(WorkflowBlockedError, match="policy denied node type"):
            await _submit_workflow(
                wf=_warning_workflow(),
                tool_name="run_workflow",
                success_message="ok",
                wait=False,
                client=client,
                audit=audit,
                inspector=inspector,
                progress=None,
            )

        assert not prompt_route.called
