"""Tests for server initialization and tool registration."""

from comfyui_mcp.server import mcp


class TestServerSetup:
    def test_server_has_name(self):
        assert mcp.name == "ComfyUI"

    def test_server_lists_tools(self):
        tools = mcp._tool_manager.list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "list_models",
            "list_nodes",
            "get_node_info",
            "list_workflows",
            "get_history",
            "get_history_item",
            "get_queue",
            "get_job",
            "cancel_job",
            "interrupt",
            "upload_image",
            "get_image",
            "list_outputs",
            "run_workflow",
            "generate_image",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
