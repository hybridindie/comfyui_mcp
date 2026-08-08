---
paths:
  - "src/comfyui_mcp/**/*.py"
---

# Architecture & Code Rules

## Layout

```
src/comfyui_mcp/
├── server.py              # MCP server entry, wires all components
├── config.py              # Pydantic settings, YAML loading, env overrides
├── client.py              # Async HTTP client for ComfyUI API (centralized)
├── audit.py               # Structured JSON audit logger
├── model_manager.py       # Lazy Model Manager detection and folder caching
├── model_registry.py      # Canonical model loader field registry
├── node_manager.py        # ComfyUI Manager detector
├── progress.py            # WebSocket progress tracking with HTTP polling fallback
├── pagination.py          # Offset-based pagination helper for list tools
├── security/              # inspector, node_auditor, sanitizer, rate_limit, ...
├── workflow/              # templates, operations, validation
└── tools/                 # generation, workflow, jobs, discovery, history, files, models, nodes
```

Keep tool behavior in `tools/*.py` and transport/API details in `client.py`.
HTTP API access is centralized in `client.py` — tools never call httpx
directly.

## Code rules

7. **No duplicate tools.** Each tool must have a unique purpose. Before adding
   a new tool, check if an existing tool already covers the same ComfyUI
   endpoint. Two tools calling the same client method is a bug.
8. **No dead code.** No placeholder methods, no unused config fields, no
   unreachable branches. If a field or method isn't used, don't add it. If it
   stops being used, remove it.
9. **All imports at the top of the file.** No deferred imports inside function
   bodies unless the dependency is optional and heavy. stdlib modules are never
   deferred.
10. **`_build_server()` returns
    `tuple[FastMCP, Settings, ComfyUIClient, httpx.AsyncClient]`.** The
    module-level `mcp`, `_settings`, `_client`, and `_search_http` are built
    once. `main()` reuses `_settings` — never call `load_settings()` a second
    time. `host`/`port` transport settings belong on `mcp.run()` /
    `mcp.http_app()`, not on the `FastMCP()` constructor (FastMCP 4 moved them
    off the constructor).
11. **Tool registration functions return `dict[str, Any]`.** Every
    `register_*_tools()` must return a dict mapping tool names to their callable
    functions. This is how tests invoke tools directly. **Alternatively**,
    tools may be defined as module-level decorated functions using
    `Depends()` for dependency injection — `Depends()` parameters are
    auto-excluded from the MCP schema and resolve at runtime. Both patterns are
    valid; pick one and be consistent within a module.
12. **Tools that always return structured data must return `dict[str, Any]`
    (not `json.dumps`).** FastMCP auto-generates `outputSchema` from the return
    type. Tools with mixed return paths (sometimes string, sometimes JSON) stay
    as `-> str`. When a tool returns a dict, tests access values directly
    (`result["key"]`) instead of `json.loads(result)["key"]`.
13. **Use `Annotated[type, Field(...)]` for tool parameters with constraints.**
    Tools with 3+ parameters should use Pydantic `Field` annotations to expose
    constraints (`ge`, `le`, `min_length`, etc.) and descriptions in the MCP tool
    JSON schema. Define reusable type aliases (e.g. `StepsField`, `CfgField`)
    for parameters shared across tools.

## Cross-cutting concerns: middleware vs. in-tool calls

FastMCP 4 middleware can centralize rate limiting, audit logging, and error
handling across every tool. The security invariants (rules 2-5 in
[[security]]) must hold regardless of *where* they are enforced:

- **Rate limiting** — either `limiter.check("tool_name")` inside each tool,
  *or* `RateLimitingMiddleware` (built-in, token-bucket) configured at the
  server level. One must be in effect for every tool.
- **Audit logging** — either `audit.async_log(...)` inside each tool, *or* a
  custom `AuditMiddleware` using the `on_call_tool` hook that emits one
  structured record per call (redacting sensitive arguments). One must be in
  effect for every tool.
- **Error handling** — `ErrorHandlingMiddleware` with `include_traceback=False`
  is the recommended default; `mask_error_details=True` on the `FastMCP()`
  constructor is equivalent.

When middleware enforces a cross-cutting concern, the per-tool boilerplate
(`limiter.check()`, `audit.async_log()`) MAY be dropped from individual tool
bodies. The invariant is "the concern is enforced for every tool call," not
"the call appears in the tool body." Tests in `test_security_invariants.py`
must be updated to assert the middleware-based enforcement path when a tool
migrates.

## Resources and prompts

FastMCP 4 supports `@mcp.resource` (including templated URIs with path-traversal
screening, on by default) and `@mcp.prompt`. Both are first-class components
alongside tools:

- **Resources** expose read-only state the LLM can browse without a tool call
  (model lists, node inventories, output metadata, queue state, whitelisted
  system info). Prefer resources for discovery that the LLM should browse
  rather than call. Templated resources like `comfyui://outputs/{filename}`
  inherit FastMCP's built-in path-traversal screening — still anchor the final
  path against an allowed root and confirm containment before reading
  (screening and containment are complementary layers).
- **Prompts** expose reusable, parameterized prompt templates (e.g. built-in
  workflow recipes). Prompt functions may return a plain string (auto-wrapped
  as a user message) or `list[Message]` for multi-turn prompts. Returning
  `mcp.types.PromptMessage` or raw `role`/`content` dicts is not supported on
  FastMCP 4 — use `from fastmcp.prompts import Message` or a plain string.

## Elicitation and background tasks (opt-in)

- **Elicitation** (`ctx.elicit()` on handshake connections, or the
  `InputRequiredResult` guard pattern on 2026-07-28 connections) lets a tool
  ask the user for input mid-execution. The workflow inspector's
  dangerous-node confirmation flow is the canonical use: gate `enforce`-mode
  warnings through elicitation so the *tool* blocks until the user confirms,
  rather than relying on the LLM to relay a soft warning. Branch on
  `ctx.request_context.protocol_version` if both eras must be served.
- **Background tasks** (`@mcp.tool(task=True)` + `TasksExtension` from
  `fastmcp[tasks]`) return a task handle immediately for long-running
  operations like `run_workflow(wait=True)`. Best suited to the
  HTTP/remote transport; stdio single-user mode gains little. Requires async
  functions only. `ctx.elicit()` is not supported inside a task — use the guard
  pattern (`InputRequiredResult`) instead.

## FastMCP 4 import and protocol notes

- Import `FastMCP`, `Context`, `Image` from `fastmcp` (not
  `mcp.server.fastmcp`). `mcp.types.ToolAnnotations` fields are snake_case in
  SDK v2 (`inputSchema` → `input_schema`, `mimeType` → `mime_type`); the
  `ToolAnnotations(readOnlyHint=..., destructiveHint=..., idempotentHint=...,
  openWorldHint=...)` usage in this project is already snake_case and carries
  over unchanged.
- One FastMCP 4 server negotiates both protocol eras per connection. The
  sessionless 2026-07-28 protocol removes the server-initiated back-channel,
  so `ctx.sample()`, `ctx.sample_step()`, and `ctx.list_roots()` are gone in
  every era — call an LLM directly from the server, or return an
  `InputRequiredResult` carrying a sampling/roots request.
- `@mcp.tool` / `@mcp.resource` / `@mcp.prompt` decorators return the original
  function unchanged (FastMCP 1.0 replaced the function with a `FunctionTool`).
  Do not read `.name` / `.description` off the decorated result — reach the
  component through `await mcp.get_tool("name")` when needed.

## Adding a new client method (checklist)

1. Verify the ComfyUI endpoint is not on the blocked list (see [[security]]
   rule 1).
2. Add the method to `ComfyUIClient` in `client.py`.
3. Use `self._request(method, path, ...)` — this handles retries on connection
   errors.
4. Add a test in `test_client.py` with `@respx.mock`.

## Adding a new security check (checklist)

1. Add to the appropriate module in `security/`.
2. Wire it in `server.py` `_build_server()` and pass to tool registration.
3. Add config fields to `config.py` if needed — every field must be read
   somewhere.
4. Add tests in `tests/test_*.py`.

## ComfyUI-Model-Manager API notes

The [ComfyUI-Model-Manager](https://github.com/hayden-fr/ComfyUI-Model-Manager)
plugin wraps all its responses in a `{"success": bool, "data": <payload>}`
envelope. The MCP client normalizes this in
`_unwrap_model_manager_response()` before returning data to callers. All
`respx` mocks for Model Manager endpoints must use this shape.

Two known quirks discovered against the live API:

1. **`previewFile` is always required** — `POST /model-manager/model` calls
   `save_model_preview()` server-side regardless. Omitting the field causes the
   task to be silently deleted with a misleading "Task not found" error. The
   client always sends `previewFile` (empty string is fine).
2. **Completed tasks stay as `pause`** — After a download finishes, the task
   remains in the list with `status: "pause"` and `progress: 100`. This is
   upstream behavior. Use `cancel_download` (which calls
   `DELETE /model-manager/download/{task_id}`) to remove it.

## Maintaining the dangerous nodes list

The `_DEFAULT_DANGEROUS_NODES` list in `config.py` contains real ComfyUI custom
node `class_type` values grouped by threat category (code execution, network
access, filesystem access). To audit a new custom node package:

1. Check the package source for calls to `exec`, `eval`, `subprocess`,
   `os.system`, `open()`, `requests`, `urllib`, or `httpx`.
2. Look for nodes that accept arbitrary file paths, URLs, or code as input.
3. Add confirmed dangerous nodes to the appropriate category in
   `_DEFAULT_DANGEROUS_NODES` with a comment noting the source package and
   reason.
4. If the node follows a naming pattern not yet covered, add a regex to
   `_DANGEROUS_NAME_PATTERNS` in `node_auditor.py`.
5. Add tests for any new patterns.
