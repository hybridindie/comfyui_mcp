"""Tests for /node_replacements endpoint and inspector integration (#111)."""

import httpx
import pytest
import respx

from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from tests.conftest import _real_get_node_replacements

_SAMPLE_REPLACEMENTS = {
    "OldLoaderNode": [
        {
            "old_node_id": "OldLoaderNode",
            "new_node_id": "NewLoaderNode",
        },
    ],
    "DeprecatedSampler": [
        {
            "old_node_id": "DeprecatedSampler",
            "new_node_id": "KSampler",
        },
    ],
}

_SAMPLE_MULTI_REPLACEMENTS = {
    "AmbiguousNode": [
        {"old_node_id": "AmbiguousNode", "new_node_id": "ReplacementA"},
        {"old_node_id": "AmbiguousNode", "new_node_id": "ReplacementB"},
    ],
}


@pytest.fixture
def client():
    return ComfyUIClient(base_url="http://test-comfyui:8188")


# Opt out of the shared autouse fixture that stubs get_node_replacements —
# these tests exercise the real client method against respx mocks.
@pytest.fixture(autouse=True)
def _mock_node_replacements(monkeypatch):
    monkeypatch.setattr(
        ComfyUIClient,
        "get_node_replacements",
        _real_get_node_replacements,
    )


# ---------------------------------------------------------------------------
# Client method
# ---------------------------------------------------------------------------


class TestClientNodeReplacements:
    @respx.mock
    async def test_get_node_replacements(self, client):
        respx.get("http://test-comfyui:8188/node_replacements").mock(
            return_value=httpx.Response(200, json=_SAMPLE_REPLACEMENTS)
        )
        result = await client.get_node_replacements()
        assert "OldLoaderNode" in result
        assert result["OldLoaderNode"][0]["new_node_id"] == "NewLoaderNode"

    @respx.mock
    async def test_get_node_replacements_empty(self, client):
        respx.get("http://test-comfyui:8188/node_replacements").mock(
            return_value=httpx.Response(200, json={})
        )
        result = await client.get_node_replacements()
        assert result == {}


# ---------------------------------------------------------------------------
# Inspector integration — warn when a submitted class_type has a replacement
# ---------------------------------------------------------------------------


class TestInspectorNodeReplacementWarning:
    def test_inspector_warns_when_class_type_has_replacement(self):
        """The inspector must warn when a submitted class_type is in the
        replacement map — what executes may differ from what was vetted."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=[],
            allowed_nodes=[],
        )
        workflow = {
            "1": {"class_type": "OldLoaderNode", "inputs": {}},
            "2": {"class_type": "KSampler", "inputs": {"cfg": 7.0}},
        }
        result = inspector.inspect(workflow, node_replacements=_SAMPLE_REPLACEMENTS)
        assert any("OldLoaderNode" in w and "replacement" in w.lower() for w in result.warnings), (
            "class_type with a server-side replacement did not produce a warning (issue #111)"
        )

    def test_inspector_no_warning_when_no_replacements_overlap(self):
        """No warning when the workflow's class_types are not in the replacement map."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=[],
            allowed_nodes=[],
        )
        workflow = {
            "1": {"class_type": "KSampler", "inputs": {"cfg": 7.0}},
        }
        result = inspector.inspect(workflow, node_replacements=_SAMPLE_REPLACEMENTS)
        assert not any("replacement" in w.lower() for w in result.warnings)

    def test_inspector_no_warning_when_replacements_empty(self):
        """No warning when the replacement map is empty."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=[],
            allowed_nodes=[],
        )
        workflow = {
            "1": {"class_type": "KSampler", "inputs": {}},
        }
        result = inspector.inspect(workflow, node_replacements={})
        assert not any("replacement" in w.lower() for w in result.warnings)

    def test_inspector_no_warning_when_replacements_none(self):
        """No warning when no replacement map is provided (backward compat)."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=[],
            allowed_nodes=[],
        )
        workflow = {
            "1": {"class_type": "KSampler", "inputs": {}},
        }
        result = inspector.inspect(workflow)
        assert not any("replacement" in w.lower() for w in result.warnings)

    def test_inspector_warns_for_multiple_replaced_nodes(self):
        """Multiple replaced class_types each produce a warning."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=[],
            allowed_nodes=[],
        )
        workflow = {
            "1": {"class_type": "OldLoaderNode", "inputs": {}},
            "2": {"class_type": "DeprecatedSampler", "inputs": {}},
        }
        result = inspector.inspect(workflow, node_replacements=_SAMPLE_REPLACEMENTS)
        replacement_warnings = [w for w in result.warnings if "replacement" in w.lower()]
        assert len(replacement_warnings) == 2

    def test_inspector_subgraph_node_replacement_warning(self):
        """A replaced class_type inside a subgraph must also warn."""
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
                        "5": {"class_type": "OldLoaderNode", "inputs": {}},
                    },
                },
            },
        }
        result = inspector.inspect(workflow, node_replacements=_SAMPLE_REPLACEMENTS)
        assert any("OldLoaderNode" in w and "replacement" in w.lower() for w in result.warnings), (
            "Replaced class_type inside a subgraph did not produce a warning (issue #111)"
        )

    def test_inspector_warns_with_all_replacements_when_multiple(self):
        """When a class_type maps to multiple replacement entries, the warning
        must list every candidate — not just the first (review feedback on #156)."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=[],
            allowed_nodes=[],
        )
        workflow = {
            "1": {"class_type": "AmbiguousNode", "inputs": {}},
        }
        result = inspector.inspect(workflow, node_replacements=_SAMPLE_MULTI_REPLACEMENTS)
        replacement_warnings = [w for w in result.warnings if "replacement" in w.lower()]
        assert len(replacement_warnings) == 1
        warning = replacement_warnings[0]
        assert "ReplacementA" in warning
        assert "ReplacementB" in warning
