"""Elicitation-based consent gates for mutating tool calls (issue #205).

Workflow submission has had an enforce-mode elicitation gate since Phase 5.
This module generalises that pattern for mutations that are not workflows:
installing, updating, or uninstalling a third-party node pack, and merging
server settings. In enforce mode the user is asked before the server runs
third-party code or changes configuration; a decline, a cancel, or the
absence of an elicitation channel blocks the operation.

Audit mode never prompts — callers keep their existing audit-only behavior.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from comfyui_mcp.audit import AuditLogger


class ConsentDeniedError(Exception):
    """Raised when a required confirmation is declined or unavailable."""


async def require_confirmation(
    ctx: Context | None,
    *,
    mode: str,
    audit: AuditLogger,
    tool: str,
    prompt: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Require an explicit user confirmation in ``enforce`` mode.

    Args:
        ctx: The MCP request context, or ``None`` for direct/test callers.
        mode: ``security.mode`` — only ``"enforce"`` gates.
        audit: Audit logger for the confirmation lifecycle.
        tool: Tool name recorded in the audit trail.
        prompt: Question shown to the user; also used in the raised error.
        extra: Structured context for the audit record (never secrets).

    Raises:
        ConsentDeniedError: The user declined/cancelled, the accepted answer
            was not ``True``, or no elicitation channel exists in enforce mode.
    """
    if mode != "enforce":
        return

    payload = extra or {}
    if ctx is None:
        await audit.async_log(tool=tool, action="confirmation_unavailable", extra=payload)
        raise ConsentDeniedError(
            f"{prompt} Refusing to proceed — enforce mode requires user "
            "confirmation and no elicitation channel is available."
        )

    await audit.async_log(tool=tool, action="eliciting_confirmation", extra=payload)
    result = await ctx.elicit(message=prompt, response_type=bool)
    action = getattr(result, "action", None)
    accepted = action == "accept" and getattr(result, "data", None) is True
    if not accepted:
        await audit.async_log(
            tool=tool,
            action="elicitation_declined",
            extra={**payload, "elicitation_action": action},
        )
        raise ConsentDeniedError(f"Declined by user — {prompt}")

    await audit.async_log(tool=tool, action="confirmed", extra=payload)
