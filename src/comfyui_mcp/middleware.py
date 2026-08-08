"""FastMCP 4 middleware: centralized rate limiting, audit logging, and error handling.

Phase 3 of the FastMCP 4 migration. Replaces the hand-rolled cross-cutting
boilerplate (``limiter.check("tool_name")`` + ``audit.async_log(...,
action="called")``) that was repeated in every tool body. Per architecture.md
"Cross-cutting concerns: middleware vs. in-tool calls", the security
invariants (rules 2-5) hold regardless of *where* they are enforced.

This middleware enforces:
  - **Rate limiting** (security rule 3) — per-category token-bucket via the
    existing ``RateLimiter``, keyed by tool name. The category for each tool
    is supplied via ``tool_categories`` (built from config.py rate_limits.*).
  - **Entry audit logging** (security rule 4) — one structured record per
    tool call with the tool name and redacted arguments, action="called".

Tools retain their domain-specific lifecycle audit logs (``submitted``,
``completed``, ``inspected``, etc.) — those carry context the middleware
cannot synthesize (prompt_id, elapsed, node counts). The middleware only
replaces the generic *entry* audit + the rate-limit check.
"""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext

from comfyui_mcp.audit import AuditLogger, _redact_sensitive
from comfyui_mcp.security.rate_limit import RateLimiter, RateLimitError

# The default category for a tool not in tool_categories. "read" is the
# least-privileged bucket — safer than defaulting to an uncategorized/unlimited path.
_DEFAULT_CATEGORY = "read"


class SecurityMiddleware(Middleware):
    """Centralized rate limiting + entry audit logging for every tool call.

    Combines security rules 3 (rate limit) and 4 (audit log) into a single
    ``on_call_tool`` hook so the per-tool boilerplate can be dropped. Tools
    keep their domain-specific lifecycle audit calls.
    """

    def __init__(
        self,
        audit: AuditLogger,
        rate_limiters: dict[str, RateLimiter],
        tool_categories: dict[str, str],
    ) -> None:
        self._audit = audit
        self._rate_limiters = rate_limiters
        self._tool_categories = tool_categories

    def _limiter_for(self, tool_name: str) -> RateLimiter:
        category = self._tool_categories.get(tool_name, _DEFAULT_CATEGORY)
        limiter = self._rate_limiters.get(category)
        if limiter is None:
            # Fall back to the read bucket if a category is missing — never
            # silently allow an unlimited path.
            limiter = self._rate_limiters.get(_DEFAULT_CATEGORY)
        if limiter is None:
            # No limiters configured at all — refuse to run rather than skip.
            raise ToolError(f"No rate limiter configured for tool '{tool_name}'")
        return limiter

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        # For on_call_tool, context.message is the CallToolRequestParams
        # directly — it carries `name` and `arguments` as top-level fields.
        message = context.message
        tool_name = getattr(message, "name", None) or "<unknown>"
        arguments = getattr(message, "arguments", None) or {}

        # Security rule 3: rate limit. A ToolError surfaces to the client as an
        # error result; RateLimitError is caught and converted so the client
        # sees a clean error rather than an internal traceback.
        limiter = self._limiter_for(tool_name)
        try:
            limiter.check(tool_name)
        except RateLimitError as e:
            raise ToolError(str(e)) from e

        # Security rule 4: entry audit. Redact sensitive arguments before
        # logging — never log raw secrets. _redact_sensitive drops keys
        # matching sensitive patterns (token, password, api_key, ...).
        redacted: dict[str, object] = (
            _redact_sensitive(dict(arguments)) if isinstance(arguments, dict) else {}
        )
        await self._audit.async_log(
            tool=tool_name,
            action="called",
            extra={"arguments": redacted},
        )

        return await call_next(context)


def build_middleware_stack(
    *,
    audit: AuditLogger,
    rate_limiters: dict[str, RateLimiter],
    tool_categories: dict[str, str],
) -> list[Middleware]:
    """Build the ordered middleware stack for the server.

    Order matters: the first added runs first on the way in, last on the way
    out. SecurityMiddleware runs early so rate limiting + audit apply to every
    call before the tool body executes.
    """
    return [
        SecurityMiddleware(
            audit=audit, rate_limiters=rate_limiters, tool_categories=tool_categories
        ),
    ]
