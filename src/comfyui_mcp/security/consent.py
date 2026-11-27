"""Elicitation-based consent gates for mutating tool calls (issues #205, #210).

Workflow submission has had an enforce-mode elicitation gate since Phase 5.
This module generalises that pattern for mutations that are not workflows:
installing, updating, or uninstalling a third-party node pack, and merging
server settings. In enforce mode the user is asked before the server runs
third-party code or changes configuration; a decline, a cancel, or the
absence of an elicitation channel blocks the operation.

Two protocol eras are served:

- **Handshake connections** (2025-*): ``ctx.elicit()`` blocks until the user
  answers.
- **Sessionless connections** (2026-07-28+): there is no server-initiated
  back-channel, so the tool returns an ``InputRequiredResult`` instead and the
  client retries the call with ``ctx.input_responses``. The gate reads the
  answer on that retry. Callers must return the guard result when the helper
  returns one.

Audit mode never prompts — callers keep their existing audit-only behavior.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context
from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult

from comfyui_mcp.audit import AuditLogger

_MODERN_PROTOCOL = "2026-07-28"
_GUARD_KEY = "approve"


class ConsentDeniedError(Exception):
    """Raised when a required confirmation is declined or unavailable."""


def uses_input_required(ctx: Context | None) -> bool:
    """True when the connection needs the ``InputRequiredResult`` guard.

    Sessionless 2026-07-28+ connections have no server-initiated request
    channel, so ``ctx.elicit()`` fails. Handshake-era connections keep using
    it. Unknown or missing context falls back to the legacy path.
    """
    if ctx is None:
        return False
    try:
        version = getattr(ctx.request_context, "protocol_version", "")
    except Exception:  # identity is best-effort; a missing context is legacy
        return False
    return isinstance(version, str) and version >= _MODERN_PROTOCOL


def request_approval(prompt: str) -> InputRequiredResult:
    """Build the boolean approval request carried by a guard result."""
    return InputRequiredResult(
        input_requests={
            _GUARD_KEY: ElicitRequest(
                params=ElicitRequestFormParams(
                    message=prompt,
                    requested_schema={
                        "type": "object",
                        "properties": {
                            "approve": {
                                "type": "boolean",
                                "title": "Approve",
                                "description": prompt,
                            }
                        },
                        "required": ["approve"],
                    },
                )
            )
        }
    )


def read_approval(ctx: Context) -> bool:
    """Read the approve/decline answer from the client's guard responses."""
    responses = ctx.input_responses or {}
    result = responses.get(_GUARD_KEY)
    if getattr(result, "action", None) != "accept":
        return False
    content = getattr(result, "content", None) or {}
    return content.get("approve") is True


async def require_confirmation(
    ctx: Context | None,
    *,
    mode: str,
    audit: AuditLogger,
    tool: str,
    prompt: str,
    extra: dict[str, Any] | None = None,
) -> InputRequiredResult | None:
    """Require an explicit user confirmation in ``enforce`` mode.

    Args:
        ctx: The MCP request context, or ``None`` for direct/test callers.
        mode: ``security.mode`` — only ``"enforce"`` gates.
        audit: Audit logger for the confirmation lifecycle.
        tool: Tool name recorded in the audit trail.
        prompt: Question shown to the user; also used in the raised error.
        extra: Structured context for the audit record (never secrets).

    Returns:
        ``None`` when the call may proceed (confirmed, or audit mode). On a
        sessionless connection's first round, an ``InputRequiredResult`` the
        caller must return as the tool result; the client retries with the
        answer.

    Raises:
        ConsentDeniedError: The user declined/cancelled, the accepted answer
            was not ``True``, or no elicitation channel exists in enforce mode.
    """
    if mode != "enforce":
        return None

    payload = extra or {}
    if ctx is None:
        await audit.async_log(tool=tool, action="confirmation_unavailable", extra=payload)
        raise ConsentDeniedError(
            f"{prompt} Refusing to proceed — enforce mode requires user "
            "confirmation and no elicitation channel is available."
        )

    if uses_input_required(ctx):
        if ctx.input_responses is None:
            await audit.async_log(
                tool=tool,
                action="eliciting_confirmation",
                extra={**payload, "channel": "input_required"},
            )
            return request_approval(prompt)
        if not read_approval(ctx):
            await audit.async_log(
                tool=tool,
                action="elicitation_declined",
                extra={**payload, "channel": "input_required"},
            )
            raise ConsentDeniedError(f"Declined by user — {prompt}")
        await audit.async_log(
            tool=tool,
            action="confirmed",
            extra={**payload, "channel": "input_required"},
        )
        return None

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
    return None
