"""ComfyUI MCP Server entry point."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from fastmcp import FastMCP

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.config import ModelSearchSettings, Settings, load_settings
from comfyui_mcp.middleware import build_middleware_stack
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
from comfyui_mcp.tools.discovery import register_discovery_tools
from comfyui_mcp.tools.files import register_file_tools
from comfyui_mcp.tools.generation import register_generation_tools
from comfyui_mcp.tools.history import register_history_tools
from comfyui_mcp.tools.jobs import register_job_tools
from comfyui_mcp.tools.models import register_model_tools
from comfyui_mcp.tools.nodes import register_node_tools
from comfyui_mcp.tools.workflow import register_workflow_tools


def _select_image_view_base_url(settings: Settings) -> str:
    """Choose image view link base URL with explicit fallback precedence."""
    external_url = settings.comfyui.external_url
    if external_url:
        return external_url

    comfyui_url = settings.comfyui.url
    if comfyui_url:
        return comfyui_url

    return "http://127.0.0.1:8188"


def _create_client(settings: Settings) -> ComfyUIClient:
    """Create and configure the ComfyUI client."""
    return ComfyUIClient(
        base_url=settings.comfyui.url,
        timeout_connect=settings.comfyui.timeout_connect,
        timeout_read=settings.comfyui.timeout_read,
        tls_verify=settings.comfyui.tls_verify,
    )


def _create_audit_logger(settings: Settings) -> AuditLogger:
    """Create and configure the audit logger."""
    audit_path = Path(settings.logging.audit_file).expanduser()
    return AuditLogger(audit_file=audit_path)


def _create_workflow_inspector(settings: Settings) -> WorkflowInspector:
    """Create and configure the workflow inspector."""
    return WorkflowInspector(
        mode=settings.security.mode,
        dangerous_nodes=settings.security.dangerous_nodes,
        allowed_nodes=settings.security.allowed_nodes,
    )


def _create_path_sanitizer(settings: Settings) -> PathSanitizer:
    """Create and configure the path sanitizer."""
    return PathSanitizer(
        allowed_extensions=settings.security.allowed_extensions,
        max_size_mb=settings.security.max_upload_size_mb,
    )


def _create_rate_limiters(settings: Settings) -> dict[str, RateLimiter]:
    """Create rate limiters for each category."""
    return {
        "workflow": RateLimiter(max_per_minute=settings.rate_limits.workflow),
        "generation": RateLimiter(max_per_minute=settings.rate_limits.generation),
        "file": RateLimiter(max_per_minute=settings.rate_limits.file_ops),
        "read": RateLimiter(max_per_minute=settings.rate_limits.read_only),
    }


# Tool-name -> rate-limit category. Mirrors the per-register_*_tools() limiter
# argument wiring so the SecurityMiddleware enforces the same per-category
# limits without the in-tool limiter.check() boilerplate. Tools not listed
# default to "read" (the least-privileged bucket) in the middleware.
_TOOL_CATEGORIES: dict[str, str] = {
    # generation tools (rate_limits.generation)
    "run_workflow": "generation",
    "run_workflow_stream": "generation",
    "generate_image": "generation",
    "transform_image": "generation",
    "inpaint_image": "generation",
    "upscale_image": "generation",
    "summarize_workflow": "read",  # uses read_limiter in generation.py
    # file tools (rate_limits.file_ops)
    "upload_image": "file",
    "get_image": "file",
    "list_outputs": "file",
    "upload_mask": "file",
    "get_workflow_from_image": "file",
    # model tools — file ops use file, reads use read
    "download_model": "file",
    "cancel_download": "file",
    "search_models": "read",
    "get_download_tasks": "read",
    # node tools — install/uninstall/update use workflow, reads use read
    "install_custom_node": "workflow",
    "uninstall_custom_node": "workflow",
    "update_custom_node": "workflow",
    "search_custom_nodes": "read",
    "get_custom_node_status": "read",
    # job tools — mutating queue ops use workflow, reads use read
    "cancel_job": "workflow",
    "interrupt": "workflow",
    "clear_queue": "workflow",
    "get_queue": "read",
    "get_queue_status": "read",
    "get_job": "read",
    "get_progress": "read",
    # discovery / history / workflow tools all use read
    "list_models": "read",
    "list_nodes": "read",
    "get_node_info": "read",
    "list_workflows": "read",
    "list_extensions": "read",
    "get_server_features": "read",
    "list_model_folders": "read",
    "get_model_metadata": "read",
    "audit_dangerous_nodes": "read",
    "get_system_info": "read",
    "get_model_presets": "read",
    "get_prompting_guide": "read",
    "get_history": "read",
    "create_workflow": "read",
    "modify_workflow": "read",
    "analyze_workflow": "read",
    "validate_workflow": "read",
    # resources and prompts use read
    "resource_models": "read",
    "resource_nodes": "read",
    "resource_queue": "read",
    "resource_system": "read",
    "prompt_txt2img": "read",
    "prompt_img2img": "read",
    "prompt_inpaint": "read",
    "prompt_upscale": "read",
}


def _register_all_tools(
    server: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    rate_limiters: dict[str, RateLimiter],
    image_view_base_url: str | None,
    inspector: WorkflowInspector,
    sanitizer: PathSanitizer,
    node_auditor: NodeAuditor,
    progress: WebSocketProgress,
    detector: ModelManagerDetector,
    model_sanitizer: PathSanitizer,
    download_validator: DownloadValidator,
    model_checker: ModelChecker,
    model_search_settings: ModelSearchSettings,
    search_http: httpx.AsyncClient,
    node_manager: ComfyUIManagerDetector,
) -> None:
    """Register all MCP tool groups with their dependencies."""
    register_discovery_tools(server, client, audit, rate_limiters["read"], sanitizer, node_auditor)
    register_history_tools(server, client, audit, rate_limiters["read"])
    register_job_tools(
        server,
        client,
        audit,
        rate_limiters["workflow"],
        read_limiter=rate_limiters["read"],
        progress=progress,
    )
    register_file_tools(
        server,
        client,
        audit,
        rate_limiters["file"],
        sanitizer,
        image_view_base_url=image_view_base_url,
    )
    register_generation_tools(
        server,
        client,
        audit,
        rate_limiters["generation"],
        inspector,
        read_limiter=rate_limiters["read"],
        progress=progress,
        model_checker=model_checker,
        sanitizer=sanitizer,
    )
    register_workflow_tools(server, client, audit, rate_limiters["read"], inspector, sanitizer)
    register_model_tools(
        mcp=server,
        client=client,
        audit=audit,
        read_limiter=rate_limiters["read"],
        file_limiter=rate_limiters["file"],
        sanitizer=model_sanitizer,
        detector=detector,
        validator=download_validator,
        search_settings=model_search_settings,
        search_http=search_http,
    )
    register_node_tools(
        mcp=server,
        client=client,
        audit=audit,
        wf_limiter=rate_limiters["workflow"],
        read_limiter=rate_limiters["read"],
        node_manager=node_manager,
        node_auditor=node_auditor,
    )
    # Resources and prompts use the read-only limiter — they mirror discovery
    # tools' cross-cutting concerns (rate limit + audit) but expose state as
    # URIs the LLM can browse without a tool call.
    register_resources(server, client, audit, rate_limiters["read"], sanitizer)
    register_prompts(server, client, audit, rate_limiters["read"], sanitizer)


def _build_server(
    settings: Settings | None = None,
) -> tuple[FastMCP, Settings, ComfyUIClient, httpx.AsyncClient]:
    """Build and configure the MCP server with all tools registered."""
    if settings is None:
        settings = load_settings()

    client = _create_client(settings)
    audit = _create_audit_logger(settings)
    inspector = _create_workflow_inspector(settings)
    sanitizer = _create_path_sanitizer(settings)
    node_auditor = NodeAuditor()
    rate_limiters = _create_rate_limiters(settings)

    # Node management dependencies
    node_manager = ComfyUIManagerDetector(client)

    # Model tools dependencies
    detector = ModelManagerDetector(client)
    model_sanitizer = PathSanitizer(
        allowed_extensions=settings.security.allowed_model_extensions,
        max_size_mb=settings.security.max_upload_size_mb,
    )
    download_validator = DownloadValidator(
        allowed_domains=settings.security.allowed_download_domains,
        allowed_extensions=settings.security.allowed_model_extensions,
    )
    model_checker = ModelChecker()
    search_http = httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10))

    server_kwargs: dict = {
        "name": "ComfyUI",
        "instructions": (
            "Secure MCP server for generating images and managing workflows via ComfyUI. "
            "Use generate_image for quick text-to-image, or run_workflow for custom workflows. "
            "Use list_models and list_nodes to discover available resources. "
            "IMPORTANT: Before running custom workflows with run_workflow, always check the "
            "response "
            "for warnings about dangerous nodes or suspicious inputs. If warnings are present, "
            "inform the user and ask for confirmation before proceeding with execution."
        ),
        "lifespan": _lifespan,
        # Phase 3: mask internal error details from clients — only ToolError
        # messages (which we control) include details. Generic exceptions get
        # a masked message rather than an internal traceback.
        "mask_error_details": True,
    }

    # FastMCP 4 moved host/port off the FastMCP() constructor to run()/http_app(),
    # so they no longer belong in server_kwargs. main() passes them to mcp.run().
    server = FastMCP(**server_kwargs)

    progress = WebSocketProgress(
        client,
        timeout=float(settings.comfyui.timeout_read),
        tls_verify=settings.comfyui.tls_verify,
    )
    _register_all_tools(
        server,
        client,
        audit,
        rate_limiters,
        _select_image_view_base_url(settings),
        inspector,
        sanitizer,
        node_auditor,
        progress,
        detector=detector,
        model_sanitizer=model_sanitizer,
        download_validator=download_validator,
        model_checker=model_checker,
        model_search_settings=settings.model_search,
        search_http=search_http,
        node_manager=node_manager,
    )

    # Phase 3: wire the middleware stack. SecurityMiddleware centralizes rate
    # limiting (security rule 3) and entry audit logging (rule 4) so the
    # per-tool limiter.check() + audit.async_log(action="called") boilerplate
    # can be dropped. Tools keep their domain-specific lifecycle audit logs.
    for mw in build_middleware_stack(
        audit=audit,
        rate_limiters=rate_limiters,
        tool_categories=_TOOL_CATEGORIES,
    ):
        server.add_middleware(mw)

    return server, settings, client, search_http


@contextlib.asynccontextmanager
async def _lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Manage async resource lifecycle for the MCP server."""
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            await _client.close()
        with contextlib.suppress(Exception):
            await _search_http.aclose()


# Module-level server instance for import and CLI use
mcp, _settings, _client, _search_http = _build_server()


def main() -> None:
    """Run the MCP server."""
    if _settings.transport.remote.enabled:
        # FastMCP 4 calls the streamable-HTTP transport "http" (not
        # "streamable-http"), and host/port now live on run() not the constructor.
        mcp.run(
            transport="http",
            host=_settings.transport.remote.host,
            port=_settings.transport.remote.port,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
