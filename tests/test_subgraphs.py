"""Tests for /global_subgraphs endpoints and subgraph insertion (#144)."""

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.discovery import register_discovery_tools
from comfyui_mcp.workflow.operations import apply_operations

_ALLOWED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".safetensors"]


@pytest.fixture
def components(tmp_path):
    client = ComfyUIClient(base_url="http://test:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    limiter = RateLimiter(max_per_minute=60)
    sanitizer = PathSanitizer(allowed_extensions=_ALLOWED_EXTENSIONS)
    return client, audit, limiter, sanitizer


@pytest.fixture
def client():
    return ComfyUIClient(base_url="http://test-comfyui:8188")


# Sample /global_subgraphs response (mirrors ComfyUI subgraph_manager.py shape)
_SAMPLE_SUBGRAPHS = {
    "abc123def456": {
        "source": "custom_node",
        "name": "txt2img_upscale_macro",
        "info": {"node_pack": "custom_nodes.my_pack"},
    },
    "789xyz012abc": {
        "source": "templates",
        "name": "basic_txt2img",
        "info": {"node_pack": "comfyui"},
    },
}

_SAMPLE_SUBGRAPH_DATA = {
    "source": "custom_node",
    "name": "txt2img_upscale_macro",
    "info": {"node_pack": "custom_nodes.my_pack"},
    "data": (
        '{"1": {"class_type": "KSampler", "inputs": {"cfg": 7.0}}, '
        '"2": {"class_type": "SaveImage", "inputs": {}}}'
    ),
}


# ---------------------------------------------------------------------------
# Client methods
# ---------------------------------------------------------------------------


class TestClientSubgraphs:
    @respx.mock
    async def test_get_global_subgraphs(self, client):
        respx.get("http://test-comfyui:8188/global_subgraphs").mock(
            return_value=httpx.Response(200, json=_SAMPLE_SUBGRAPHS)
        )
        result = await client.get_global_subgraphs()
        assert "abc123def456" in result
        assert result["abc123def456"]["name"] == "txt2img_upscale_macro"

    @respx.mock
    async def test_get_global_subgraph_single(self, client):
        respx.get("http://test-comfyui:8188/global_subgraphs/abc123def456").mock(
            return_value=httpx.Response(200, json=_SAMPLE_SUBGRAPH_DATA)
        )
        result = await client.get_global_subgraph("abc123def456")
        assert result["name"] == "txt2img_upscale_macro"
        assert "data" in result

    @respx.mock
    async def test_get_global_subgraph_not_found(self, client):
        respx.get("http://test-comfyui:8188/global_subgraphs/nonexistent").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_global_subgraph("nonexistent")


# ---------------------------------------------------------------------------
# Discovery tools
# ---------------------------------------------------------------------------


class TestListSubgraphsTool:
    @respx.mock
    async def test_list_subgraphs_returns_dict(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/global_subgraphs").mock(
            return_value=httpx.Response(200, json=_SAMPLE_SUBGRAPHS)
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)

        result = await tools["comfyui_list_subgraphs"]()
        assert "abc123def456" in result["subgraphs"]
        assert result["count"] == 2

    @respx.mock
    async def test_list_subgraphs_empty(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/global_subgraphs").mock(
            return_value=httpx.Response(200, json={})
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)

        result = await tools["comfyui_list_subgraphs"]()
        assert result["subgraphs"] == {}
        assert result["count"] == 0


class TestGetSubgraphTool:
    @respx.mock
    async def test_get_subgraph_returns_data(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/global_subgraphs/abc123def456").mock(
            return_value=httpx.Response(200, json=_SAMPLE_SUBGRAPH_DATA)
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)

        result = await tools["comfyui_get_subgraph"](subgraph_id="abc123def456")
        assert result["name"] == "txt2img_upscale_macro"
        assert "data" in result

    @respx.mock
    async def test_get_subgraph_not_found(self, components):
        client, audit, limiter, sanitizer = components
        respx.get("http://test:8188/global_subgraphs/nonexistent").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        mcp = FastMCP("test")
        tools = register_discovery_tools(mcp, client, audit, limiter, sanitizer)

        result = await tools["comfyui_get_subgraph"](subgraph_id="nonexistent")
        assert result["available"] is False


# ---------------------------------------------------------------------------
# Workflow operations — insert_subgraph
# ---------------------------------------------------------------------------


class TestInsertSubgraphOperation:
    def test_insert_subgraph_adds_subgraph_node(self):
        workflow = {
            "1": {"class_type": "KSampler", "inputs": {"cfg": 7.0}},
        }
        subgraph_nodes = {
            "10": {"class_type": "KSampler", "inputs": {"cfg": 8.0}},
            "11": {"class_type": "SaveImage", "inputs": {}},
        }
        result = apply_operations(
            workflow,
            [
                {
                    "op": "insert_subgraph",
                    "class_type": "Reroute_subgraph",
                    "subgraph_nodes": subgraph_nodes,
                },
            ],
        )
        assert "2" in result
        assert result["2"]["class_type"] == "Reroute_subgraph"
        assert result["2"]["inputs"]["subgraph"] == subgraph_nodes

    def test_insert_subgraph_with_custom_node_id(self):
        workflow = {}
        subgraph_nodes = {"10": {"class_type": "KSampler", "inputs": {}}}
        result = apply_operations(
            workflow,
            [
                {
                    "op": "insert_subgraph",
                    "class_type": "Reroute_subgraph",
                    "subgraph_nodes": subgraph_nodes,
                    "node_id": "99",
                },
            ],
        )
        assert "99" in result
        assert result["99"]["class_type"] == "Reroute_subgraph"

    def test_insert_subgraph_requires_subgraph_nodes(self):
        workflow = {}
        with pytest.raises(ValueError, match="subgraph_nodes"):
            apply_operations(
                workflow,
                [{"op": "insert_subgraph", "class_type": "Reroute_subgraph"}],
            )


# ---------------------------------------------------------------------------
# Inspector integration — a subgraph inserted via operations must be scanned
# ---------------------------------------------------------------------------


class TestInsertedSubgraphInspection:
    def test_inspector_flags_dangerous_node_in_inserted_subgraph(self):
        """When a subgraph with a dangerous node is inserted into a workflow,
        the inspector must flag it (the #110 recursion fix)."""
        inspector = WorkflowInspector(
            mode="audit",
            dangerous_nodes=["Terminal"],
            allowed_nodes=[],
        )
        workflow = {
            "1": {"class_type": "KSampler", "inputs": {"cfg": 7.0}},
        }
        subgraph_nodes = {
            "10": {"class_type": "Terminal", "inputs": {}},
        }
        result_wf = apply_operations(
            workflow,
            [
                {
                    "op": "insert_subgraph",
                    "class_type": "Reroute_subgraph",
                    "subgraph_nodes": subgraph_nodes,
                },
            ],
        )
        result = inspector.inspect(result_wf)
        assert any("Terminal" in w for w in result.warnings), (
            "Dangerous node inside an inserted subgraph was not flagged"
        )
