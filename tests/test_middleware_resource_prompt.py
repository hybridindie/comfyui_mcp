"""Tests for SecurityMiddleware coverage of resources and prompts (#136).

Verifies the middleware's on_read_resource and on_get_prompt hooks fire
for resources and prompts — closing the gap where the original on_call_tool
hook covered tools only, leaving resources/prompts enforced solely by
in-tool calls with no test guardrail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.middleware import SecurityMiddleware
from comfyui_mcp.security.rate_limit import RateLimiter


def _read_audit_lines(audit_file: Path) -> list[dict]:
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


class TestOnReadResourceHook:
    async def test_resource_read_writes_audit_record(self, tmp_path, rate_limiters):
        """on_read_resource fires for resource reads, writing an entry audit
        record keyed by the resource URI — not just the on_call_tool path."""
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        middleware = SecurityMiddleware(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={},
        )
        mcp = FastMCP("test")

        @mcp.resource("comfyui://models/checkpoints")
        async def models_resource() -> str:
            return json.dumps({"models": ["a.safetensors"]})

        mcp.add_middleware(middleware)

        result = await mcp.read_resource("comfyui://models/checkpoints")
        assert result.contents  # the read succeeded
        records = _read_audit_lines(tmp_path / "audit.log")
        assert any(r["action"] == "called" for r in records), (
            "on_read_resource did not write an entry audit record — resources "
            "have no enforcement coverage without this hook (security rule 4)"
        )

    async def test_resource_read_rate_limited(self, tmp_path, rate_limiters):
        """on_read_resource enforces the rate limit — a second read past the
        bucket is blocked (security rule 3 for resources)."""
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        rate_limiters["read"] = RateLimiter(max_per_minute=1)
        middleware = SecurityMiddleware(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={},
        )
        mcp = FastMCP("test")

        @mcp.resource("comfyui://test")
        async def r() -> str:
            return "ok"

        mcp.add_middleware(middleware)
        first = await mcp.read_resource("comfyui://test")
        assert first.contents
        from fastmcp.exceptions import ResourceError

        with pytest.raises(ResourceError, match="Rate limit exceeded"):
            await mcp.read_resource("comfyui://test")


class TestOnGetPromptHook:
    async def test_prompt_get_writes_audit_record(self, tmp_path, rate_limiters):
        """on_get_prompt fires for prompt retrieval, writing an entry audit
        record keyed by the prompt name — security rule 4 for prompts."""
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        middleware = SecurityMiddleware(
            audit=audit,
            rate_limiters=rate_limiters,
            tool_categories={},
        )
        mcp = FastMCP("test")

        @mcp.prompt
        def greeting(name: str) -> str:
            return f"hi {name}"

        mcp.add_middleware(middleware)
        result = await mcp.render_prompt("greeting", {"name": "world"})
        assert result  # the render succeeded
        records = _read_audit_lines(tmp_path / "audit.log")
        assert any(r["action"] == "called" for r in records), (
            "on_get_prompt did not write an entry audit record — prompts have "
            "no enforcement coverage without this hook (security rule 4)"
        )
