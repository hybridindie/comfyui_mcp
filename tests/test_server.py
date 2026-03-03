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
            "list_extensions",
            "get_server_features",
            "list_model_folders",
            "get_model_metadata",
            "audit_dangerous_nodes",
            "get_history",
            "get_history_item",
            "get_queue",
            "get_job",
            "cancel_job",
            "interrupt",
            "get_queue_status",
            "clear_queue",
            "upload_image",
            "get_image",
            "list_outputs",
            "upload_mask",
            "run_workflow",
            "generate_image",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
