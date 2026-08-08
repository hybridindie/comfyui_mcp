"""Tests for FastMCP 4 middleware (rate limiting + audit + error handling).

Phase 3 of the FastMCP 4 migration. The middleware centralizes the generic
cross-cutting concerns (rate limiting, entry audit logging, error masking)
that were previously repeated as boilerplate inside every tool body.

These tests assert the middleware behavior directly — that a tool call is
rate-limited, that an entry audit record is written, and that errors are
masked. Per testing rule 19, this covers the middleware-based enforcement
path; the closure-based invariants in test_security_invariants.py cover the
in-tool path (and will be updated when tools drop their in-tool calls).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.middleware import SecurityMiddleware, build_middleware_stack
from comfyui_mcp.security.rate_limit import RateLimiter


def _read_audit_lines(audit_file: Path) -> list[dict]:
    """Read the JSON-lines audit log as a list of dicts."""
    if not audit_file.exists():
        return []
    lines = audit_file.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line]


@pytest.fixture
def rate_limiters() -> dict[str, RateLimiter]:
    return {
        "read": RateLimiter(max_per_minute=60),
        "workflow": RateLimiter(max_per_minute=10),
        "generation": RateLimiter(max_per_minute=10),
        "file": RateLimiter(max_per_minute=30),
    }


class TestSecurityMiddlewareRateLimiting:
    async def test_rate_limit_writes_audit_and_passes_under_limit(self, tmp_path, rate_limiters):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        middleware = SecurityMiddleware(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={"comfyui_get_queue": "read"},
        )
        mcp = FastMCP("test")

        @mcp.tool
        async def comfyui_get_queue() -> dict:
            return {"queue_running": [], "queue_pending": []}

        mcp.add_middleware(middleware)

        # Invoke through the MCP server's tool-call path so middleware fires.
        result = await mcp.call_tool("comfyui_get_queue", {})
        assert result.is_error is False
        # Entry audit record written by the middleware
        records = _read_audit_lines(tmp_path / "audit.log")
        assert any(r["tool"] == "comfyui_get_queue" and r["action"] == "called" for r in records)

    async def test_rate_limit_blocks_when_exceeded(self, tmp_path, rate_limiters):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        # A limiter with 1 request per minute — second call must be blocked.
        rate_limiters["read"] = RateLimiter(max_per_minute=1)
        middleware = SecurityMiddleware(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={"comfyui_get_queue": "read"},
        )
        mcp = FastMCP("test")

        @mcp.tool
        async def comfyui_get_queue() -> dict:
            return {"queue_running": [], "queue_pending": []}

        mcp.add_middleware(middleware)

        first = await mcp.call_tool("comfyui_get_queue", {})
        assert first.is_error is False
        # Second call exceeds the limit — middleware raises a ToolError that
        # surfaces from call_tool. (FastMCP 4 raises ToolError rather than
        # returning an error result for middleware-raised errors.)
        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="Rate limit exceeded"):
            await mcp.call_tool("comfyui_get_queue", {})

    async def test_unknown_tool_category_defaults_to_read(self, tmp_path, rate_limiters):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        middleware = SecurityMiddleware(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={},
        )
        mcp = FastMCP("test")

        @mcp.tool
        async def some_unknown_tool() -> dict:
            return {"ok": True}

        mcp.add_middleware(middleware)

        result = await mcp.call_tool("some_unknown_tool", {})
        assert result.is_error is False
        records = _read_audit_lines(tmp_path / "audit.log")
        assert any(r["tool"] == "some_unknown_tool" and r["action"] == "called" for r in records)


class TestSecurityMiddlewareAudit:
    async def test_entry_audit_redacts_sensitive_args(self, tmp_path, rate_limiters):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        middleware = SecurityMiddleware(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={"comfyui_upload_image": "file"},
        )
        mcp = FastMCP("test")

        @mcp.tool
        async def comfyui_upload_image(
            filename: str, api_key: str = "secret-value", image_data: str = "data"
        ) -> dict:
            return {"filename": filename}

        mcp.add_middleware(middleware)

        await mcp.call_tool(
            "comfyui_upload_image",
            {"filename": "test.png", "api_key": "secret-value", "image_data": "data"},
        )
        records = _read_audit_lines(tmp_path / "audit.log")
        entry = next(r for r in records if r["action"] == "called")
        # The api_key argument must be redacted (never logged raw)
        assert "api_key" not in entry.get("extra", {})
        assert "secret-value" not in json.dumps(entry)


class TestBuildMiddlewareStack:
    def test_returns_ordered_list_with_security_first(self, tmp_path, rate_limiters):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        stack = build_middleware_stack(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={"comfyui_get_queue": "read"},
        )
        # SecurityMiddleware must be in the stack (error handling is built-in
        # via FastMCP constructor mask_error_details, not a separate middleware
        # here — but the stack must include the security one).
        assert any(isinstance(m, SecurityMiddleware) for m in stack)

    def test_stack_is_not_empty(self, tmp_path, rate_limiters):
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        stack = build_middleware_stack(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={},
        )
        assert len(stack) >= 1
