---
type: reference
title: "Server & middleware"
description: "The FastMCP 4 server, the middleware stack, dependency injection, and how registration works."
created: 2026-10-06
updated: 2026-10-06
---

# Server & middleware

## Entry point

`server.py` builds everything in `_build_server()`, which returns
`tuple[FastMCP, Settings, ComfyUIClient, httpx.AsyncClient]` — the module
objects are built once and reused. Transports: stdio by default;
Streamable HTTP when `transport.remote.enabled` (host/port go to `mcp.run()`,
not the constructor — a FastMCP 4 change).

At startup, the server lifespan fetches the ComfyUI `/features` dict once
and records it into the audit trail (`action: "server_features"`) so
runs against capability-differing servers are distinguishable. Failures are
debug-logged and non-fatal.

## The middleware stack

`SecurityMiddleware` is the custom one (rate limit + entry audit via the
FastMCP 4 `on_call_tool` hook, sensitive arguments redacted). Alongside it,
built-in FastMCP 4 middleware covers cross-cutting behavior:

| Middleware | Purpose |
|---|---|
| `SecurityMiddleware` (custom) | Per-call rate-limit check + entry audit record, args redacted |
| `ResponseCachingMiddleware` | Caches read-only tools + the 5 `comfyui://` resources, 30s TTL |
| `ResponseLimitingMiddleware` | Caps `list_nodes` / `list_models` / `get_history` payloads at 500KB |
| `PingMiddleware` | Keeps long-lived HTTP connections alive |
| `StructuredLoggingMiddleware` | Ops/observability logging, `include_payloads=False` (the AuditLogger redacts) |

Error details are masked at the constructor
(`mask_error_details=True`): clients see only `ToolError` messages the
server chose to send, not tracebacks.

## Cross-cutting enforcement: in-tool or middleware

The security invariants (rate limiting, audit logging) must hold for every
tool call — but *where* is a module decision. Tools may call
`limiter.check()` / `audit.async_log()` themselves, or rely on the
middleware. The invariant tests assert enforcement fires either way; the
middleware now carries the entry records, tool bodies keep lifecycle
records (`submitted`, `completed`, `upload_rejected`, ...). When an audit
record must exist is part of the contract, not an implementation detail.

## Dependency injection

`dependencies.py` exposes `Depends()` providers for the singletons —
`client`, `audit`, `inspector`, `limiter` — configured at startup.
`Depends()` parameters are auto-excluded from the MCP tool schema and
resolved at runtime. Two registration patterns coexist:

- Factory: `register_*_tools()` functions return `dict[str, Any]` mapping
  tool names to callables (tests invoke them directly)
- DI: module-level `@mcp.tool()` functions with `Depends()` parameters

Both are pinned by invariant tests; the DI version of `get_history`
(`tools/history_di.py`) is the canonical example of the second pattern.

## Registration surfaces

One server instance registers all four component kinds:

- 53 tools across 8 modules under `tools/`
- 5 resources (`resources.py`) — browsing URIs, templated with
  path-traversal screening
- 4 prompts (`prompts.py`) — workflow recipes
- optional `TasksExtension` when `tasks.enabled`