---
paths:
  - "src/comfyui_mcp/tools/**/*.py"
  - "src/comfyui_mcp/server.py"
---

# Tool Contract & Adding New Tools

Every `@mcp.tool()` MUST:

- Be rate-limited — either `limiter.check("tool_name")` inside the body, *or*
  `RateLimitingMiddleware` at the server level (see [[security]] rule 3). One
  must be in effect for every tool.
- Be audit-logged — either `audit.async_log(...)` inside the body, *or* a
  custom `AuditMiddleware` using the `on_call_tool` hook (see [[security]]
  rule 4). One must be in effect for every tool.
- If it handles files: validate filenames/subfolders through `sanitizer`
  (see [[security]] rule 2).
- If it submits workflows: inspect through `inspector` before
  `client.post_prompt()` (see [[security]] rule 5).
- Use `Annotated[type, Field(...)]` for parameters with constraints (3+ params)
  (see [[architecture]] rule 13).
- Return `dict[str, Any]` if all code paths return structured data; use `-> str`
  only for mixed return paths (see [[architecture]] rule 12).
- Have a docstring written for an agent: what it does, when to use it, what it
  returns. This is the client-facing description.

Dependencies that should not appear in the tool schema (HTTP clients, sanitizers,
inspectors, rate limiters, audit loggers) may be injected via `Depends()` —
FastMCP auto-excludes `Depends()` parameters from the schema and resolves them
at runtime. See [[architecture]] "Cross-cutting concerns" for the middleware
alternative to in-tool `limiter.check()` / `audit.async_log()` calls.

## Adding a new tool (checklist)

1. Add the tool function in the appropriate `tools/*.py`.
2. Use `@mcp.tool()` decorator with a clear docstring.
3. Ensure rate limiting is in effect (in-tool `limiter.check()` OR
   `RateLimitingMiddleware`).
4. Ensure audit logging is in effect (in-tool `audit.async_log()` OR
   `AuditMiddleware`).
5. If it handles files: validate through `sanitizer`.
6. If it submits workflows: inspect through `inspector`.
7. Use `Annotated[type, Field(...)]` for parameters with constraints (3+ params).
8. Return `dict[str, Any]` if all code paths return structured data; use
   `-> str` only for mixed return paths.
9. Either add the function to the `tool_fns` dict and return it, *or* define
   it as a module-level decorated function with `Depends()` for DI.
10. Wire it in `server.py` `_register_all_tools()` if it uses the factory
    pattern and needs new dependencies. (Module-level decorated functions with
    `Depends()` skip this step — the decorator registers them.)
11. Add tests in `tests/test_tools_*.py` that call the function directly.
12. Update the Tools table in `README.md`.

## Anti-patterns

- Two tools calling the same client method (duplicate tool — see
  [[architecture]] rule 7).
- A tool that returns `json.dumps(...)` when every code path is structured
  (breaks `outputSchema` generation and forces `json.loads` in tests).
- A `@mcp.tool()` body that reaches into `client.py` transport details instead
  of calling a `ComfyUIClient` method.
