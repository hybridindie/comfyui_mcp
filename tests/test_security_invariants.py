"""Static invariants for CLAUDE.md security rules 2-5.

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

import inspect
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.config import ModelSearchSettings
from comfyui_mcp.model_manager import ModelManagerDetector
from comfyui_mcp.node_manager import ComfyUIManagerDetector
from comfyui_mcp.progress import WebSocketProgress
from comfyui_mcp.security.download_validator import DownloadValidator
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.model_checker import ModelChecker
from comfyui_mcp.security.node_auditor import NodeAuditor
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer
from comfyui_mcp.tools.discovery import register_discovery_tools
from comfyui_mcp.tools.files import register_file_tools
from comfyui_mcp.tools.generation import register_generation_tools
from comfyui_mcp.tools.history import register_history_tools
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
# WorkflowInspector per CLAUDE.md rule 5.
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
def all_tools(tmp_path: Any) -> dict[str, Any]:
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
    tools.update(register_history_tools(mcp, client, audit, rl_read))
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
    return tools


def _closure_values(fn: Any) -> Iterator[Any]:
    """Yield every nonlocal value captured by ``fn``'s closure."""
    yield from inspect.getclosurevars(fn).nonlocals.values()


def _has_instance_of(fn: Any, cls: type) -> bool:
    """True if any closure variable of ``fn`` is an instance of ``cls``."""
    return any(isinstance(v, cls) for v in _closure_values(fn))


class TestRateLimiterInvariant:
    """CLAUDE.md rule 3: All tools must go through the rate limiter."""

    def test_every_tool_has_a_rate_limiter_in_closure(self, all_tools: dict[str, Any]) -> None:
        missing = [name for name, fn in all_tools.items() if not _has_instance_of(fn, RateLimiter)]
        assert not missing, (
            f"{len(missing)} tool(s) have no RateLimiter in closure — "
            f"cannot enforce CLAUDE.md rule 3: {sorted(missing)}"
        )


class TestAuditInvariant:
    """CLAUDE.md rule 4: All tools must audit log."""

    def test_every_tool_has_an_audit_logger_in_closure(self, all_tools: dict[str, Any]) -> None:
        missing = [name for name, fn in all_tools.items() if not _has_instance_of(fn, AuditLogger)]
        assert not missing, (
            f"{len(missing)} tool(s) have no AuditLogger in closure — "
            f"cannot enforce CLAUDE.md rule 4: {sorted(missing)}"
        )


class TestSanitizerInvariant:
    """CLAUDE.md rule 2: All file-handling tools must use PathSanitizer."""

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
            f"cannot enforce CLAUDE.md rule 2: {sorted(missing)}"
        )


class TestInspectorInvariant:
    """CLAUDE.md rule 5: Workflow execution must go through the inspector."""

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
            f"cannot enforce CLAUDE.md rule 5: {sorted(missing)}"
        )
