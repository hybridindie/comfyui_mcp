"""Post-replacement inspection (issue #206).

ComfyUI rewrites submitted ``class_type``s through ``/node_replacements``
after the inspector runs. These tests pin that the effective node — class and
remapped inputs — is inspected too, so a benign submission cannot become a
dangerous execution after vetting.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import (
    WorkflowBlockedError,
    WorkflowInspector,
    uses_server_replacement,
)
from comfyui_mcp.tools.generation import _submit_workflow
from tests.conftest import _real_get_node_replacements


@pytest.fixture(autouse=True)
def _mock_node_replacements(monkeypatch):
    """Exercise the real client method; the shared fixture stubs it to {}."""
    monkeypatch.setattr(
        ComfyUIClient,
        "get_node_replacements",
        _real_get_node_replacements,
    )


def _node(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def _replacement(new_node_id: str, mapping: list[dict] | None = None) -> dict:
    entry = {
        "new_node_id": new_node_id,
        "old_node_id": "Old",
        "output_mapping": [{"new_idx": 0, "old_idx": 0}],
    }
    if mapping is not None:
        entry["input_mapping"] = mapping
    return entry


def _warned(warnings: list[str], fragment: str) -> bool:
    return any(fragment in warning for warning in warnings)


class TestReplacementReinspection:
    def test_dangerous_replacement_target_is_flagged(self):
        inspector = WorkflowInspector(mode="audit", dangerous_nodes=["ExecutePython"])
        wf = {"1": _node("Old", images="a.png")}

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [_replacement("ExecutePython", [])]},
            known_node_types={"ExecutePython"},
        )

        assert _warned(result.warnings, "Dangerous node type after server-side replacement")
        assert _warned(result.warnings, "ExecutePython")

    def test_set_value_is_inspected(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("Old")}
        mapping = [{"new_id": "code", "set_value": "eval('import os')"}]

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [_replacement("New", mapping)]},
            known_node_types={"New"},
        )

        assert _warned(result.warnings, "Suspicious input in node 1 (New), field 'code'")

    def test_renamed_input_is_inspected(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("Old", script="exec('payload')")}
        mapping = [{"new_id": "code", "old_id": "script"}]

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [_replacement("New", mapping)]},
            known_node_types={"New"},
        )

        assert _warned(result.warnings, "Suspicious input in node 1 (New), field 'code'")

    def test_missing_mapped_input_is_reported(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("Old")}
        mapping = [{"new_id": "image", "old_id": "images"}]

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [_replacement("New", mapping)]},
            known_node_types={"New"},
        )

        assert _warned(result.warnings, "mapped input 'images' is absent")

    def test_unknown_target_is_reported(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("Old")}

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [_replacement("NotInstalled", [])]},
            known_node_types={"SomethingElse"},
        )

        assert _warned(result.warnings, "Replacement target 'NotInstalled'")
        assert _warned(result.warnings, "is not installed")

    def test_known_target_is_not_reported_as_missing(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("Old")}

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [_replacement("New", [])]},
            known_node_types={"New"},
        )

        assert not _warned(result.warnings, "is not installed")

    def test_missing_input_mapping_falls_back_to_submitted_inputs(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("Old", text="eval('x')")}

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [_replacement("New")]},
            known_node_types={"New"},
        )

        assert _warned(result.warnings, "replacement has no input mapping")
        assert _warned(result.warnings, "Suspicious input in node 1 (New), field 'text'")

    def test_malformed_replacement_is_reported(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("Old")}

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [{"old_node_id": "Old"}]},
            known_node_types=None,
        )

        assert _warned(result.warnings, "malformed server-side replacement")

    def test_duplicate_replacements_warn_once(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("Old"), "2": _node("Old")}

        result = inspector.inspect(
            wf,
            node_replacements={"Old": [_replacement("New", [])]},
            known_node_types={"New"},
        )

        generic = [w for w in result.warnings if "has server-side replacement" in w]
        assert len(generic) == 1

    def test_no_replacements_changes_nothing(self):
        inspector = WorkflowInspector(mode="audit")
        wf = {"1": _node("KSampler", seed=1)}

        result = inspector.inspect(wf, node_replacements=None)

        assert result.warnings == []
        assert result.nodes_used == ["KSampler"]


class TestUsesServerReplacement:
    def test_detects_top_level(self):
        assert uses_server_replacement({"1": _node("Old")}, {"Old": [_replacement("New")]})

    def test_detects_inside_inline_subgraph(self):
        wf = {
            "1": _node(
                "Subgraph",
                subgraph={"2": _node("Old", images="a.png")},
            )
        }
        assert uses_server_replacement(wf, {"Old": [_replacement("New")]})

    def test_false_when_no_match(self):
        assert not uses_server_replacement({"1": _node("Other")}, {"Old": [_replacement("New")]})


class TestSubmitWorkflowFetchesObjectInfo:
    @respx.mock
    async def test_unknown_replacement_target_surfaces_in_warnings(self, tmp_path):
        client = ComfyUIClient(base_url="http://test:8188")
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        inspector = WorkflowInspector(mode="audit")

        respx.get("http://test:8188/node_replacements").mock(
            return_value=httpx.Response(
                200,
                json={"Old": [_replacement("NotInstalled", [])]},
            )
        )
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {}})
        )
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )

        result = await _submit_workflow(
            wf={"1": _node("Old")},
            tool_name="run_workflow",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=None,
        )

        assert result["status"] == "submitted"
        assert _warned(result["warnings"], "Replacement target 'NotInstalled'")

    @respx.mock
    async def test_object_info_skipped_when_no_replacement_applies(self, tmp_path):
        client = ComfyUIClient(base_url="http://test:8188")
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        inspector = WorkflowInspector(mode="audit")

        respx.get("http://test:8188/node_replacements").mock(
            return_value=httpx.Response(200, json={"Old": [_replacement("New", [])]})
        )
        object_info = respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {}})
        )
        respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )

        await _submit_workflow(
            wf={"1": _node("KSampler", seed=1)},
            tool_name="run_workflow",
            success_message="ok",
            wait=False,
            client=client,
            audit=audit,
            inspector=inspector,
            progress=None,
        )

        assert not object_info.called


class TestEnforceModeBlocksDangerousReplacement:
    @respx.mock
    async def test_enforce_blocks_when_replacement_is_dangerous(self, tmp_path):
        client = ComfyUIClient(base_url="http://test:8188")
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        inspector = WorkflowInspector(mode="enforce", dangerous_nodes=["ExecutePython"])

        respx.get("http://test:8188/node_replacements").mock(
            return_value=httpx.Response(
                200,
                json={"Old": [_replacement("ExecutePython", [])]},
            )
        )
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"ExecutePython": {}})
        )
        prompt_route = respx.post("http://test:8188/prompt").mock(
            return_value=httpx.Response(200, json={"prompt_id": "abc-123"})
        )

        with pytest.raises(
            WorkflowBlockedError,
            match="Dangerous node type after server-side replacement",
        ):
            await _submit_workflow(
                wf={"1": _node("Old")},
                tool_name="run_workflow",
                success_message="ok",
                wait=False,
                client=client,
                audit=audit,
                inspector=inspector,
                progress=None,
            )

        assert not prompt_route.called
