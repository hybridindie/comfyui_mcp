"""Dependency-injection providers for FastMCP 4 Depends().

Phase 4 of the FastMCP 4 migration. Lets tools declare their dependencies as
``Depends(get_client)`` parameters (auto-excluded from the MCP schema) instead
of receiving them as positional args through register_*_tools() factories.

The providers resolve the module-level singletons built by ``_build_server()``
in ``server.py``. They are set once at startup via ``configure_dependencies()``
so each provider returns the live instance. Tests can re-configure with test
doubles.

This is opt-in per-tool-module: a tool module may keep its register_*_tools()
factory OR define module-level decorated functions using these providers.
Both patterns are valid per architecture.md rule 11.
"""

from __future__ import annotations

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.security.inspector import WorkflowInspector
from comfyui_mcp.security.model_checker import ModelChecker
from comfyui_mcp.security.rate_limit import RateLimiter
from comfyui_mcp.security.sanitizer import PathSanitizer

# Module-level singleton slots. Populated by configure_dependencies() at
# server startup (server.py:_build_server) and by tests with their own
# instances. A provider raises if called before configuration — fail loud
# rather than silently returning None.
_client: ComfyUIClient | None = None
_audit: AuditLogger | None = None
_inspector: WorkflowInspector | None = None
_sanitizer: PathSanitizer | None = None
_model_checker: ModelChecker | None = None
_read_limiter: RateLimiter | None = None
_workflow_limiter: RateLimiter | None = None
_generation_limiter: RateLimiter | None = None
_file_limiter: RateLimiter | None = None


def configure_dependencies(
    *,
    client: ComfyUIClient,
    audit: AuditLogger,
    inspector: WorkflowInspector,
    sanitizer: PathSanitizer,
    model_checker: ModelChecker,
    read_limiter: RateLimiter,
    workflow_limiter: RateLimiter,
    generation_limiter: RateLimiter,
    file_limiter: RateLimiter,
) -> None:
    """Populate the module-level singleton slots. Called once at startup."""
    global _client, _audit, _inspector, _sanitizer, _model_checker
    global _read_limiter, _workflow_limiter, _generation_limiter, _file_limiter
    _client = client
    _audit = audit
    _inspector = inspector
    _sanitizer = sanitizer
    _model_checker = model_checker
    _read_limiter = read_limiter
    _workflow_limiter = workflow_limiter
    _generation_limiter = generation_limiter
    _file_limiter = file_limiter


def reset_dependencies() -> None:
    """Clear the singleton slots. For test isolation between modules."""
    global _client, _audit, _inspector, _sanitizer, _model_checker
    global _read_limiter, _workflow_limiter, _generation_limiter, _file_limiter
    _client = None
    _audit = None
    _inspector = None
    _sanitizer = None
    _model_checker = None
    _read_limiter = None
    _workflow_limiter = None
    _generation_limiter = None
    _file_limiter = None


def get_client() -> ComfyUIClient:
    """Resolve the ComfyUI HTTP client singleton."""
    if _client is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _client


def get_audit() -> AuditLogger:
    """Resolve the audit logger singleton."""
    if _audit is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _audit


def get_inspector() -> WorkflowInspector:
    """Resolve the workflow inspector singleton."""
    if _inspector is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _inspector


def get_sanitizer() -> PathSanitizer:
    """Resolve the path sanitizer singleton."""
    if _sanitizer is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _sanitizer


def get_model_checker() -> ModelChecker:
    """Resolve the model checker singleton."""
    if _model_checker is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _model_checker


def get_read_limiter() -> RateLimiter:
    """Resolve the read-only rate limiter singleton."""
    if _read_limiter is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _read_limiter


def get_workflow_limiter() -> RateLimiter:
    """Resolve the workflow rate limiter singleton."""
    if _workflow_limiter is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _workflow_limiter


def get_generation_limiter() -> RateLimiter:
    """Resolve the generation rate limiter singleton."""
    if _generation_limiter is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _generation_limiter


def get_file_limiter() -> RateLimiter:
    """Resolve the file-ops rate limiter singleton."""
    if _file_limiter is None:
        raise RuntimeError("Dependencies not configured — call configure_dependencies() first")
    return _file_limiter
