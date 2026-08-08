"""Static invariants for security rules 2-5.

Verifies every registered MCP tool has access to the required security
primitives via its closure. This converts the per-call conventions for rate
limiting, audit logging, path sanitization, and workflow inspection from
"enforced by checklist" to "structurally enforced at registration time".

Approach: each tool function returned by ``register_*_tools()`` is a closure
over its enclosing scope. ``inspect.getclosurevars(fn).nonlocals`` returns
exactly those captured names. A tool that lacks the security primitive in its
closure cannot call it, transitively or otherwise.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.config import ModelSearchSettings
from comfyui_mcp.model_manager import ModelManagerDetector
from comfyui_mcp.node_manager import ComfyUIManagerDetector
from comfyui_mcp.progress import WebSocketProgress
from comfyui_mcp.prompts import register_prompts
from comfyui_mcp.resources import register_resources
from comfyui_mcp.security.download_validator import DownloadValidator
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.model_checker import ModelChecker
from comfyui_mcp.security.node_auditor import NodeAuditor
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools import history_di
from comfyui_mcp.tools.discovery import register_discovery_tools
from comfyui_mcp.tools.files import register_file_tools
from comfyui_mcp.tools.generation import register_generation_tools
from comfyui_mcp.tools.jobs import register_job_tools
from comfyui_mcp.tools.models import register_model_tools
from comfyui_mcp.tools.nodes import register_node_tools
from comfyui_mcp.tools.workflow import register_workflow_tools

# Tools that take a filename, subfolder, folder, or template-param input that
# resolves to a path-like value. Adding a tool here without wiring sanitizer
# into its closure will fail test_file_handling_tools_have_sanitizer.
FILE_HANDLING_TOOLS: frozenset[str] = frozenset(
    {
        "comfyui_list_models",
        "comfyui_get_model_metadata",
        "comfyui_upload_image",
        "comfyui_get_image",
        "comfyui_upload_mask",
        "comfyui_get_workflow_from_image",
        "comfyui_transform_image",
        "comfyui_inpaint_image",
        "comfyui_upscale_image",
        "comfyui_download_model",
        "comfyui_create_workflow",
    }
)

# Tools that submit a workflow via client.post_prompt() — must go through the
# WorkflowInspector per security rule 5.
WORKFLOW_SUBMITTING_TOOLS: frozenset[str] = frozenset(
    {
        "comfyui_run_workflow",
        "comfyui_run_workflow_stream",
        "comfyui_generate_image",
        "comfyui_transform_image",
        "comfyui_inpaint_image",
        "comfyui_upscale_image",
    }
)


@pytest.fixture
def all_tools(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Build every tool from every register_*_tools() with real wiring.

    Mirrors server.py:_build_server() but skips FastMCP transport setup.
    No HTTP traffic occurs — closures are inspected, not invoked.
    """
    client = ComfyUIClient(base_url="http://mock-comfyui:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    inspector = WorkflowInspector(mode="audit", dangerous_nodes=[], allowed_nodes=[])
    sanitizer = PathSanitizer(allowed_extensions=[".png", ".jpg", ".json"])
    model_sanitizer = PathSanitizer(allowed_extensions=[".safetensors", ".gguf"])
    node_auditor = NodeAuditor()
    model_checker = ModelChecker()
    download_validator = DownloadValidator(
        allowed_domains=["huggingface.co"],
        allowed_extensions=[".safetensors", ".gguf"],
    )
    detector = ModelManagerDetector(client)
    node_manager = ComfyUIManagerDetector(client)
    progress = WebSocketProgress(client)
    search_http = httpx.AsyncClient()
    model_search_settings = ModelSearchSettings()

    rl_workflow = RateLimiter(max_per_minute=10)
    rl_generation = RateLimiter(max_per_minute=10)
    rl_file = RateLimiter(max_per_minute=30)
    rl_read = RateLimiter(max_per_minute=60)

    mcp = FastMCP("invariants-test")

    tools: dict[str, Any] = {}
    tools.update(register_discovery_tools(mcp, client, audit, rl_read, sanitizer, node_auditor))
    # history is the DI version (history_di.register) — the factory was removed in #138.
    # The DI tool is not in the tools dict (it has no closure to inspect), but the
    # sanitizer/inspector invariants below only cover factory tools, and the
    # middleware-invocation tests (TestRateLimiterInvariant/TestAuditInvariant)
    # cover the DI tool's enforcement via the SecurityMiddleware path.
    history_di.register(mcp)
    tools.update(
        register_job_tools(mcp, client, audit, rl_workflow, read_limiter=rl_read, progress=progress)
    )
    tools.update(register_file_tools(mcp, client, audit, rl_file, sanitizer))
    tools.update(
        register_generation_tools(
            mcp,
            client,
            audit,
            rl_generation,
            inspector,
            read_limiter=rl_read,
            progress=progress,
            model_checker=model_checker,
            sanitizer=sanitizer,
        )
    )
    tools.update(register_workflow_tools(mcp, client, audit, rl_read, inspector, sanitizer))
    tools.update(
        register_model_tools(
            mcp=mcp,
            client=client,
            audit=audit,
            read_limiter=rl_read,
            file_limiter=rl_file,
            sanitizer=model_sanitizer,
            detector=detector,
            validator=download_validator,
            search_settings=model_search_settings,
            search_http=search_http,
        )
    )
    tools.update(
        register_node_tools(
            mcp=mcp,
            client=client,
            audit=audit,
            wf_limiter=rl_workflow,
            read_limiter=rl_read,
            node_manager=node_manager,
            node_auditor=node_auditor,
        )
    )
    try:
        yield tools
    finally:
        # search_http is captured in closures but never invoked here
        # (we only inspect closures). Close it anyway to avoid unclosed-client
        # ResourceWarnings during the test run.
        asyncio.run(search_http.aclose())


def _closure_values(fn: Any) -> Iterator[Any]:
    """Yield every nonlocal value captured by ``fn``'s closure."""
    yield from inspect.getclosurevars(fn).nonlocals.values()


def _has_instance_of(fn: Any, cls: type) -> bool:
    """True if any closure variable of ``fn`` is an instance of ``cls``."""
    return any(isinstance(v, cls) for v in _closure_values(fn))


class TestRateLimiterInvariant:
    """Security rule 3: All tools must be rate-limited.

    The in-tool limiter.check() boilerplate was removed (#137); enforcement
    is now via SecurityMiddleware.on_call_tool. This test proves the middleware
    fires end-to-end via mcp.call_tool (not just that the limiter is in the
    closure — the old closure test only proved capture, not invocation, and
    silently passed even when the check was removed).
    """

    @respx.mock
    async def test_middleware_enforces_rate_limit_for_tool(self, tmp_path: Path) -> None:
        import httpx

        from comfyui_mcp.middleware import build_middleware_stack

        client = ComfyUIClient(base_url="http://test:8188")
        audit = AuditLogger(audit_file=tmp_path / "audit.log")
        sanitizer = PathSanitizer(allowed_extensions=[".png", ".json"])
        node_auditor = NodeAuditor()
        rl_read = RateLimiter(max_per_minute=1)  # exhaust after 1 call
        rl_workflow = RateLimiter(max_per_minute=10)
        rl_generation = RateLimiter(max_per_minute=10)
        rl_file = RateLimiter(max_per_minute=30)
        mcp = FastMCP("invariants-middleware-test")
        register_discovery_tools(mcp, client, audit, rl_read, sanitizer, node_auditor)
        for mw in build_middleware_stack(
            audit=audit,
            rate_limiters={
                "read": rl_read,
                "workflow": rl_workflow,
                "generation": rl_generation,
                "file": rl_file,
            },
            tool_categories={"comfyui_list_nodes": "read"},
        ):
            mcp.add_middleware(mw)
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {}})
        )
        # First call succeeds
        first = await mcp.call_tool("comfyui_list_nodes", {"limit": 25, "offset": 0})
        assert first.is_error is False
        # Second call exceeds the 1/min limit — middleware raises ToolError
        from fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="Rate limit exceeded"):
            await mcp.call_tool("comfyui_list_nodes", {"limit": 25, "offset": 0})


class TestAuditInvariant:
    """Security rule 4: All tools must audit log.

    The in-tool entry audit (action=\"called\") was removed (#137); the entry
    record is now written by SecurityMiddleware.on_call_tool. This test proves
    the middleware writes the audit record end-to-end.
    """

    @respx.mock
    async def test_middleware_writes_entry_audit_for_tool(self, tmp_path: Path) -> None:
        import json as _json

        import httpx

        from comfyui_mcp.middleware import build_middleware_stack

        client = ComfyUIClient(base_url="http://test:8188")
        audit_path = tmp_path / "audit.log"
        audit = AuditLogger(audit_file=audit_path)
        sanitizer = PathSanitizer(allowed_extensions=[".png", ".json"])
        node_auditor = NodeAuditor()
        rl_read = RateLimiter(max_per_minute=60)
        mcp = FastMCP("invariants-audit-test")
        register_discovery_tools(mcp, client, audit, rl_read, sanitizer, node_auditor)
        for mw in build_middleware_stack(
            audit=audit,
            rate_limiters={
                "read": rl_read,
                "workflow": RateLimiter(max_per_minute=10),
                "generation": RateLimiter(max_per_minute=10),
                "file": RateLimiter(max_per_minute=30),
            },
            tool_categories={"comfyui_list_nodes": "read"},
        ):
            mcp.add_middleware(mw)
        respx.get("http://test:8188/object_info").mock(
            return_value=httpx.Response(200, json={"KSampler": {}})
        )
        await mcp.call_tool("comfyui_list_nodes", {"limit": 25, "offset": 0})
        records = []
        if audit_path.exists():
            records = [_json.loads(line) for line in audit_path.read_text().splitlines() if line]
        assert any(
            r["tool"] == "comfyui_list_nodes" and r["action"] == "called" for r in records
        ), (
            "SecurityMiddleware did not write the entry audit record — the "
            "on_call_tool hook must fire for every tool call (security rule 4)"
        )


class TestSanitizerInvariant:
    """Security rule 2: All file-handling tools must use PathSanitizer."""

    def test_file_handling_tools_have_sanitizer_in_closure(self, all_tools: dict[str, Any]) -> None:
        unknown = FILE_HANDLING_TOOLS - all_tools.keys()
        assert not unknown, (
            f"FILE_HANDLING_TOOLS lists tool(s) that no longer exist: {sorted(unknown)}. "
            "Update the allowlist."
        )
        missing = [
            name
            for name in FILE_HANDLING_TOOLS
            if not _has_instance_of(all_tools[name], PathSanitizer)
        ]
        assert not missing, (
            f"{len(missing)} file-handling tool(s) have no PathSanitizer in closure — "
            f"cannot enforce security rule 2: {sorted(missing)}"
        )


class TestInspectorInvariant:
    """Security rule 5: Workflow execution must go through the inspector."""

    def test_workflow_submitting_tools_have_inspector_in_closure(
        self, all_tools: dict[str, Any]
    ) -> None:
        unknown = WORKFLOW_SUBMITTING_TOOLS - all_tools.keys()
        assert not unknown, (
            f"WORKFLOW_SUBMITTING_TOOLS lists tool(s) that no longer exist: {sorted(unknown)}. "
            "Update the allowlist."
        )
        missing = [
            name
            for name in WORKFLOW_SUBMITTING_TOOLS
            if not _has_instance_of(all_tools[name], WorkflowInspector)
        ]
        assert not missing, (
            f"{len(missing)} workflow-submitting tool(s) have no WorkflowInspector in closure — "
            f"cannot enforce security rule 5: {sorted(missing)}"
        )


# --- Resources and prompts (#136) ---
# The all_tools fixture above covers factory tools only. Resources and prompts
# are registered separately and need their own closure invariant check —
# without this, removing their in-tool limiter/audit calls (which the
# SecurityMiddleware on_read_resource/on_get_prompt hooks now cover) would
# not be caught by any test.


@pytest.fixture
def all_components(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Build the resource and prompt functions with real wiring."""
    client = ComfyUIClient(base_url="http://mock-comfyui:8188")
    audit = AuditLogger(audit_file=tmp_path / "audit.log")
    sanitizer = PathSanitizer(allowed_extensions=[".png", ".jpg", ".json"])
    rl_read = RateLimiter(max_per_minute=60)
    mcp = FastMCP("invariants-components-test")
    components: dict[str, Any] = {}
    components.update(register_resources(mcp, client, audit, rl_read, sanitizer))
    components.update(register_prompts(mcp, client, audit, rl_read, sanitizer))
    yield components


class TestResourceRateLimiterInvariant:
    """Security rule 3 for resources: each resource closure must have a
    RateLimiter (in-tool enforcement path). The middleware on_read_resource
    hook is the framework path; both are covered."""

    def test_resources_have_rate_limiter_in_closure(self, all_components: dict[str, Any]) -> None:
        resource_fns = {k: v for k, v in all_components.items() if k.startswith("comfyui_")}
        assert resource_fns, "No resource functions registered — fixture is broken"
        missing = [
            name for name, fn in resource_fns.items() if not _has_instance_of(fn, RateLimiter)
        ]
        assert not missing, (
            f"{len(missing)} resource(s) have no RateLimiter in closure — "
            f"cannot enforce security rule 3 for resources: {sorted(missing)}"
        )


class TestResourceAuditInvariant:
    """Security rule 4 for resources: each resource closure must have an
    AuditLogger."""

    def test_resources_have_audit_logger_in_closure(self, all_components: dict[str, Any]) -> None:
        resource_fns = {k: v for k, v in all_components.items() if k.startswith("comfyui_")}
        missing = [
            name for name, fn in resource_fns.items() if not _has_instance_of(fn, AuditLogger)
        ]
        assert not missing, (
            f"{len(missing)} resource(s) have no AuditLogger in closure — "
            f"cannot enforce security rule 4 for resources: {sorted(missing)}"
        )


class TestPromptRateLimiterInvariant:
    """Security rule 3 for prompts."""

    def test_prompts_have_rate_limiter_in_closure(self, all_components: dict[str, Any]) -> None:
        prompt_fns = {k: v for k, v in all_components.items() if k.endswith("_prompt")}
        assert prompt_fns, "No prompt functions registered — fixture is broken"
        missing = [name for name, fn in prompt_fns.items() if not _has_instance_of(fn, RateLimiter)]
        assert not missing, (
            f"{len(missing)} prompt(s) have no RateLimiter in closure — "
            f"cannot enforce security rule 3 for prompts: {sorted(missing)}"
        )


class TestPromptAuditInvariant:
    """Security rule 4 for prompts."""

    def test_prompts_have_audit_logger_in_closure(self, all_components: dict[str, Any]) -> None:
        prompt_fns = {k: v for k, v in all_components.items() if k.endswith("_prompt")}
        missing = [name for name, fn in prompt_fns.items() if not _has_instance_of(fn, AuditLogger)]
        assert not missing, (
            f"{len(missing)} prompt(s) have no AuditLogger in closure — "
            f"cannot enforce security rule 4 for prompts: {sorted(missing)}"
        )
