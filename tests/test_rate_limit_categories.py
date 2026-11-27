"""Rate-limit categories must resolve for `comfyui_*` tool names (issue #238)."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.config import Settings
from comfyui_mcp.middleware import SecurityMiddleware
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.server import _TOOL_CATEGORIES, _build_server


def _limiters(*, generation: int = 10) -> dict[str, RateLimiter]:
    return {
        "workflow": RateLimiter(max_per_minute=10),
        "generation": RateLimiter(max_per_minute=generation),
        "file": RateLimiter(max_per_minute=30),
        "read": RateLimiter(max_per_minute=60),
    }


class TestResolution:
    async def test_generation_tool_uses_the_generation_bucket(self, tmp_path):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        mcp = FastMCP("rate-category-test")

        @mcp.tool
        async def comfyui_generate_image() -> dict:
            return {"ok": True}

        mcp.add_middleware(
            SecurityMiddleware(
                audit=audit,
                rate_limiters=_limiters(generation=1),
                tool_categories={"generate_image": "generation"},
            )
        )

        first = await mcp.call_tool("comfyui_generate_image", {})
        assert first.is_error is False

        with pytest.raises(ToolError, match="Rate limit exceeded"):
            await mcp.call_tool("comfyui_generate_image", {})

    async def test_unlisted_tool_falls_back_to_read(self, tmp_path):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        mcp = FastMCP("rate-category-fallback")

        @mcp.tool
        async def comfyui_some_new_tool() -> dict:
            return {"ok": True}

        limiters = _limiters()
        limiters["read"] = RateLimiter(max_per_minute=1)
        mcp.add_middleware(
            SecurityMiddleware(audit=audit, rate_limiters=limiters, tool_categories={})
        )

        first = await mcp.call_tool("comfyui_some_new_tool", {})
        assert first.is_error is False

        with pytest.raises(ToolError, match="Rate limit exceeded"):
            await mcp.call_tool("comfyui_some_new_tool", {})


class TestMapIntegrity:
    @pytest.mark.parametrize(
        ("tool", "category"),
        [
            ("comfyui_run_workflow", "generation"),
            ("comfyui_generate_image", "generation"),
            ("comfyui_upload_image", "file"),
            ("comfyui_install_custom_node", "workflow"),
            ("comfyui_get_queue", "read"),
        ],
    )
    def test_category_map_covers_representative_tools(self, tool, category):
        assert _TOOL_CATEGORIES[tool.removeprefix("comfyui_")] == category

    async def test_every_category_key_names_a_registered_tool(self):
        server, *_ = _build_server(settings=Settings())

        names = {tool.name for tool in await server.list_tools()}
        missing = {f"comfyui_{name}" for name in _TOOL_CATEGORIES} - names

        assert not missing, f"category map names unknown tools: {sorted(missing)}"
