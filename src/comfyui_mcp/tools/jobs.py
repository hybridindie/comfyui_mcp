"""Job management tools: get_queue, get_job, cancel_job, interrupt, get_progress."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from comfyui_mcp.audit import AuditLogger
from comfyui_mcp.client import ComfyUIClient
from comfyui_mcp.progress import WebSocketProgress
from comfyui_mcp.security.rate_limit import RateLimiter


def register_job_tools(
    mcp: FastMCP,
    client: ComfyUIClient,
    audit: AuditLogger,
    limiter: RateLimiter,
    *,
    read_limiter: RateLimiter | None = None,
    progress: WebSocketProgress | None = None,
) -> dict[str, Any]:
    """Register job management tools."""
    tool_fns: dict[str, Any] = {}

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_get_queue() -> dict[str, Any]:
        """Get the current ComfyUI execution queue state."""
        rl = read_limiter if read_limiter is not None else limiter
        rl.check("get_queue")
        await audit.async_log(tool="get_queue", action="called")
        return await client.get_queue()

    tool_fns["comfyui_get_queue"] = comfyui_get_queue

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_get_job(prompt_id: str) -> dict[str, Any]:
        """Look up a single job by prompt_id across queue + history.

        Returns the unified job object: status (pending/in_progress/completed/failed),
        timing, outputs, etc. Use this to check on a job that may be queued, running,
        or already finished.
        """
        rl = read_limiter if read_limiter is not None else limiter
        rl.check("get_job")
        await audit.async_log(tool="get_job", action="called", extra={"prompt_id": prompt_id})
        return await client.get_job(prompt_id)

    tool_fns["comfyui_get_job"] = comfyui_get_job

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_list_jobs(
        status: Annotated[
            list[Literal["pending", "in_progress", "completed", "failed"]] | None,
            Field(
                default=None,
                description="Filter by job status (any combination).",
            ),
        ] = None,
        workflow_id: Annotated[
            str | None,
            Field(default=None, description="Filter by workflow ID set in extra_data."),
        ] = None,
        sort_by: Annotated[
            Literal["created_at", "execution_duration"],
            Field(default="created_at", description="Sort field."),
        ] = "created_at",
        sort_order: Annotated[
            Literal["asc", "desc"],
            Field(default="desc", description="Sort direction."),
        ] = "desc",
        limit: Annotated[
            int | None,
            Field(default=None, ge=1, le=1000, description="Max jobs to return."),
        ] = None,
        offset: Annotated[
            int,
            Field(default=0, ge=0, description="Jobs to skip for pagination."),
        ] = 0,
    ) -> dict[str, Any]:
        """List jobs across queue and history with filtering, sorting, and pagination.

        Returns {"jobs": [...], "pagination": {"offset", "limit", "total", "has_more"}}.
        Each job includes prompt_id, status (pending/in_progress/completed/failed),
        timing, and outputs (when completed).
        """
        rl = read_limiter if read_limiter is not None else limiter
        rl.check("list_jobs")
        await audit.async_log(
            tool="list_jobs",
            action="called",
            extra={
                "status": status,
                "workflow_id": workflow_id,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "limit": limit,
                "offset": offset,
            },
        )
        return await client.get_jobs(
            status=list(status) if status is not None else None,
            workflow_id=workflow_id,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    tool_fns["comfyui_list_jobs"] = comfyui_list_jobs

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_cancel_job(prompt_id: str) -> str:
        """Cancel a running or queued job by its prompt_id."""
        limiter.check("cancel_job")
        await audit.async_log(tool="cancel_job", action="called", extra={"prompt_id": prompt_id})
        await client.delete_queue_item(prompt_id)
        return f"Cancelled job {prompt_id}"

    tool_fns["comfyui_cancel_job"] = comfyui_cancel_job

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_interrupt(prompt_id: str | None = None) -> str:
        """Interrupt the currently executing workflow.

        Without prompt_id: global interrupt — stops whatever is running now.
        With prompt_id: targeted — only interrupts if that prompt is the
        running one. ComfyUI silently no-ops if prompt_id is queued but
        not yet running.
        """
        limiter.check("interrupt")
        await audit.async_log(tool="interrupt", action="called", extra={"prompt_id": prompt_id})
        await client.interrupt(prompt_id=prompt_id)
        if prompt_id is None:
            return "Interrupted current execution (global)"
        return f"Requested interrupt for prompt {prompt_id} (no-op if not running)"

    tool_fns["comfyui_interrupt"] = comfyui_interrupt

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_get_queue_status() -> dict[str, Any]:
        """Get detailed queue status including currently running and pending prompts."""
        rl = read_limiter if read_limiter is not None else limiter
        rl.check("get_queue_status")
        await audit.async_log(tool="get_queue_status", action="called")
        return await client.get_prompt_status()

    tool_fns["comfyui_get_queue_status"] = comfyui_get_queue_status

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_clear_queue(clear_running: bool = False, clear_pending: bool = True) -> str:
        """Clear items from the execution queue.

        Args:
            clear_running: Stop the currently running workflow
            clear_pending: Remove pending workflows from the queue
        """
        limiter.check("clear_queue")
        await audit.async_log(
            tool="clear_queue",
            action="called",
            extra={"clear_running": clear_running, "clear_pending": clear_pending},
        )
        await client.clear_queue(clear_running=clear_running, clear_pending=clear_pending)
        return f"Queue cleared (running={clear_running}, pending={clear_pending})"

    tool_fns["comfyui_clear_queue"] = comfyui_clear_queue

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def comfyui_get_progress(prompt_id: str) -> dict[str, Any]:
        """Get the current execution progress for a workflow via HTTP.

        Returns status (queued/running/completed/error/unknown), queue position,
        and output files when available. Step progress and current node are only
        available when using wait=True on run_workflow/generate_image (WebSocket).

        Args:
            prompt_id: The prompt_id returned by run_workflow or generate_image.
        """
        progress_limiter = read_limiter if read_limiter is not None else limiter
        progress_limiter.check("get_progress")
        await audit.async_log(tool="get_progress", action="called", extra={"prompt_id": prompt_id})
        if progress is None:
            return {
                "prompt_id": prompt_id,
                "status": "unknown",
                "error": "Progress tracking not configured",
            }
        state = await progress.get_state(prompt_id)
        return state.to_dict()

    tool_fns["comfyui_get_progress"] = comfyui_get_progress

    return tool_fns
