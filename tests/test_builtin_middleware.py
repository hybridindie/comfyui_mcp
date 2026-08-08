"""Tests for built-in FastMCP 4 middleware wired in #139.

Verifies ResponseCachingMiddleware (cache hit skips the ComfyUI round-trip),
ResponseLimitingMiddleware (large payloads truncated), PingMiddleware
(present and does not break flows), and StructuredLoggingMiddleware (present).
These complement the custom SecurityMiddleware (#125).
"""

from __future__ import annotations

import httpx
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.middleware import build_middleware_stack
from comfyui_mcp.security.rate_limit import RateLimiter


def _rate_limiters() -> dict[str, RateLimiter]:
    return {
        "read": RateLimiter(max_per_minute=600),
        "workflow": RateLimiter(max_per_minute=600),
        "generation": RateLimiter(max_per_minute=600),
        "file": RateLimiter(max_per_minute=600),
    }


class TestBuildMiddlewareStackIncludesBuiltins:
    def test_stack_includes_response_caching(self, tmp_path):
        from fastmcp.server.middleware.caching import ResponseCachingMiddleware

        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        stack = build_middleware_stack(
            audit=audit, rate_limiters=_rate_limiters(), tool_categories={}
        )
        assert any(isinstance(m, ResponseCachingMiddleware) for m in stack), (
            "ResponseCachingMiddleware not in the stack — read-only tools/resources "
            "won't be cached, and the bespoke _OBJECT_INFO_TTL cache can't be dropped"
        )

    def test_stack_includes_response_limiting(self, tmp_path):
        from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware

        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        stack = build_middleware_stack(
            audit=audit, rate_limiters=_rate_limiters(), tool_categories={}
        )
        assert any(isinstance(m, ResponseLimitingMiddleware) for m in stack), (
            "ResponseLimitingMiddleware not in the stack — large list_nodes/list_models/"
            "get_history payloads can blow LLM context with no framework-level cap"
        )

    def test_stack_includes_ping(self, tmp_path):
        from fastmcp.server.middleware import PingMiddleware

        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        stack = build_middleware_stack(
            audit=audit, rate_limiters=_rate_limiters(), tool_categories={}
        )
        assert any(isinstance(m, PingMiddleware) for m in stack)

    def test_stack_includes_structured_logging(self, tmp_path):
        from fastmcp.server.middleware.logging import StructuredLoggingMiddleware

        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        stack = build_middleware_stack(
            audit=audit, rate_limiters=_rate_limiters(), tool_categories={}
        )
        assert any(isinstance(m, StructuredLoggingMiddleware) for m in stack)


class TestResponseCachingBehavior:
    @respx.mock
    async def test_cached_tool_skips_second_round_trip(self, tmp_path):
        """A cached read-only tool does not hit the ComfyUI API on the second
        call within the TTL — the bespoke _OBJECT_INFO_TTL cache is no longer
        needed once this middleware covers the object_info-backed tools."""
        from fastmcp.server.middleware.caching import ResponseCachingMiddleware

        client = ComfyUIClient(base_url="http://test:8188")
        AuditLogger(audit_file=tmp_path / "audit.log")
        _rate_limiters()
        mcp = FastMCP("test")

        @mcp.tool
        async def comfyui_list_nodes(limit: int = 25, offset: int = 0) -> dict:
            info = await client.get_object_info()
            return {"items": sorted(info.keys())[offset : offset + limit], "total": len(info)}

        mcp.add_middleware(
            ResponseCachingMiddleware(
                call_tool_settings={"included_tools": ["comfyui_list_nodes"], "ttl": 30}
            )
        )
        route = respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {}, "CLIPTextEncode": {}})
        )
        first = await mcp.call_tool("comfyui_list_nodes", {"limit": 25, "offset": 0})
        assert first.is_error is False
        assert route.calls.call_count == 1
        # Second call within TTL — should be served from cache, no new HTTP call
        second = await mcp.call_tool("comfyui_list_nodes", {"limit": 25, "offset": 0})
        assert second.is_error is False
        assert route.calls.call_count == 1, (
            f"ResponseCachingMiddleware did not cache — second call hit the API "
            f"(call count {route.calls.call_count})"
        )


class TestResponseLimitingBehavior:
    async def test_large_response_truncated(self, tmp_path):
        """A tool response exceeding max_size is truncated with the suffix."""
        from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware

        mcp = FastMCP("test")

        @mcp.tool
        async def big_tool() -> str:
            return "x" * 10_000

        mcp.add_middleware(ResponseLimitingMiddleware(max_size=500, tools=["big_tool"]))
        result = await mcp.call_tool("big_tool", {})
        text = result.content[0].text if result.content else ""
        assert len(text) <= 600  # truncated + suffix
        assert "truncated" in text.lower()


class TestPingDoesNotBreakFlows:
    async def test_ping_present_and_tool_call_succeeds(self, tmp_path):
        """PingMiddleware is wired and does not break a normal tool call."""
        from fastmcp.server.middleware import PingMiddleware

        mcp = FastMCP("test")

        @mcp.tool
        async def simple_tool() -> dict:
            return {"ok": True}

        mcp.add_middleware(PingMiddleware(interval_ms=60000))
        result = await mcp.call_tool("simple_tool", {})
        assert result.is_error is False
